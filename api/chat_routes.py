"""
核心聊天与检索 API

路由:
- POST /chat        - 普通聊天模式（JSON 响应）
- POST /rag         - 知识库问答模式（SSE 流式返回）
- POST /search      - 混合检索接口（供 Dify 调用）

注意：
- 会话管理由后端负责，RAG 服务不存储对话历史
- 权限验证由后端网关完成
- /rag 接口已升级为 SSE 流式返回，不再返回阻塞 JSON
"""

import json
import os
import queue
import threading
import time as _time

import numpy as np
from flask import Blueprint, request, jsonify, Response, current_app
from auth.gateway import require_gateway_auth

from auth.security import validate_query, filter_response
from config import RAG_CHAT_MODEL

chat_bp = Blueprint('chat', __name__)


def _get_agentic_rag():
    return current_app.config['AGENTIC_RAG']


def _attach_citations(answer: str, contexts: list) -> dict:
    """
    自动为回答添加引用（不依赖 LLM 标注）

    流程：
    1. 将 answer 按句子分割
    2. 对每个句子计算与各 context 的相似度
    3. 相似度超过阈值则附加引用
    4. 使用 [ref:chunk_id] 占位符（前端负责重新编号）

    Args:
        answer: LLM 生成的回答
        contexts: 检索到的上下文列表

    Returns:
        {
            "answer_with_refs": "回答文本（含 [ref:chunk_id] 标记）",
            "citations": [引用列表]
        }
    """
    import re

    if not contexts:
        return {"answer_with_refs": answer, "citations": []}

    # 按 chunk_id 组织 contexts
    ctx_by_chunk = {}
    for ctx in contexts:
        meta = ctx.get('meta', {})
        chunk_id = meta.get('chunk_id') or f"{meta.get('source')}_{meta.get('chunk_index', 0)}"
        ctx_by_chunk[chunk_id] = ctx

    # 按句子分割
    sentences = re.split(r'([。！？\n])', answer)
    cited_chunks = set()  # 存储被引用的 chunk_id

    result_sentences = []
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        punctuation = sentences[i + 1] if i + 1 < len(sentences) else ''

        if len(sentence.strip()) < 10:  # 太短的句子不引用
            result_sentences.append(sentence + punctuation)
            continue

        # 关键词匹配：检查句子是否包含某个 context 的关键信息
        best_chunk_id = None
        best_score = 0

        for chunk_id, ctx in ctx_by_chunk.items():
            ctx_doc = ctx.get('doc', '')
            if not ctx_doc:
                continue

            # 简单关键词重叠匹配
            overlap = len(set(sentence) & set(ctx_doc[:200]))
            score = overlap / max(len(sentence), 1)

            if score > best_score and score > 0.3:  # 阈值
                best_score = score
                best_chunk_id = chunk_id

        if best_chunk_id:
            cited_chunks.add(best_chunk_id)
            # 使用 [ref:chunk_id] 占位符，前端负责重新编号
            result_sentences.append(f"{sentence}[ref:{best_chunk_id}]{punctuation}")
        else:
            result_sentences.append(sentence + punctuation)

    # 构建引用列表（只包含实际被引用的）
    citations = []
    for chunk_id in cited_chunks:
        ctx = ctx_by_chunk.get(chunk_id)
        if ctx:
            meta = ctx.get('meta', {})
            full_content = ctx.get('doc', '')  # 完整切片内容
            citation = _build_citation(meta, full_content)
            citations.append(citation)

    return {
        "answer_with_refs": "".join(result_sentences),
        "citations": citations
    }


def _build_citation(meta: dict, full_content: str = '') -> dict:
    """
    根据文档类型构建定位信息（差异化处理）

    PDF: 坐标定位（page + bbox）
    Word: 语义定位（section + section_chunk_id + preview）
    Excel: 表格定位（sheet + preview）
    """
    citation = {
        "chunk_id": meta.get('chunk_id'),
        "source": meta.get('source', ''),
        "doc_type": meta.get('doc_type', 'other'),
        "section": meta.get('section', ''),
        "preview": meta.get('preview', ''),
        "content": full_content or meta.get('preview', ''),  # 完整切片内容（前端可展开查看）
        "chunk_type": meta.get('chunk_type', 'text'),
    }

    doc_type = meta.get('doc_type', 'other')

    if doc_type == 'pdf':
        # PDF: 坐标定位
        bbox_raw = meta.get('bbox')
        bbox = None
        if bbox_raw:
            try:
                bbox = json.loads(bbox_raw) if isinstance(bbox_raw, str) else bbox_raw
            except (json.JSONDecodeError, TypeError):
                bbox = bbox_raw

        citation.update({
            "page": meta.get('page'),
            "page_end": meta.get('page_end'),
            "bbox": bbox,
            "bbox_mode": meta.get('bbox_mode'),
        })
    elif doc_type == 'word':
        # Word: 语义定位
        citation.update({
            "section_chunk_id": meta.get('section_chunk_id'),  # 章节内段落序号
        })
    elif doc_type == 'excel':
        # Excel: 表格定位
        citation.update({
            "page": meta.get('page'),  # 工作表序号
        })
    else:
        # 其他类型：返回所有可用信息
        bbox_raw = meta.get('bbox')
        bbox = None
        if bbox_raw:
            try:
                bbox = json.loads(bbox_raw) if isinstance(bbox_raw, str) else bbox_raw
            except (json.JSONDecodeError, TypeError):
                bbox = bbox_raw

        citation.update({
            "page": meta.get('page'),
            "page_end": meta.get('page_end'),
            "bbox": bbox,
            "bbox_mode": meta.get('bbox_mode'),
        })

    return citation


def score_image_relevance(query: str, meta: dict, doc: str = '') -> float:
    """
    图片相关性打分（语义增强版）

    Args:
        query: 用户查询
        meta: 切片元数据
        doc: document 字段（包含图片描述和上下文）

    Returns:
        相关性分数（>= 3.0 推荐展示）
    """
    import re
    score = 0.0

    # 优先使用 doc 字段（包含完整描述和上下文）
    search_text = doc or meta.get('caption', '')
    section = meta.get('section', '') or meta.get('section_path', '')
    source = meta.get('source', '')

    # 1. 图片编号精确匹配（最高优先级）
    figure_pattern = r'图\s*(\d+\.?\d*)'
    figure_matches = re.findall(figure_pattern, query)

    if figure_matches:
        for fig_num in figure_matches:
            # 在所有文本中查找图号
            all_text = f"{search_text} {section} {source}"
            if f"图{fig_num}" in all_text or f"图 {fig_num}" in all_text or f"见图{fig_num}" in all_text:
                score += 10.0  # 精确匹配，直接返回
                return score

    # 1.5. 表格编号精确匹配（新增：支持表格图片）
    table_pattern = r'表\s*(\d+\.?\d*)'
    table_matches = re.findall(table_pattern, query)

    if table_matches:
        for table_num in table_matches:
            # 在所有文本中查找表号
            all_text = f"{search_text} {section} {source}"
            if f"表{table_num}" in all_text or f"表 {table_num}" in all_text or f"见表{table_num}" in all_text:
                score += 10.0  # 精确匹配，直接返回
                return score

    # 2. 查询词匹配（通用方式，不硬编码关键词）
    # 从查询中提取有意义的词：中文词组、数字+单位、年份等
    # 使用 jieba 分词（如果可用）或简单的正则提取
    query_keywords = []

    # 提取年份（如 "2003年"）
    year_matches = re.findall(r'(\d{4})\s*年', query)
    query_keywords.extend(year_matches)

    # 提取数值+单位（如 "100亿"、"50万千瓦时"）
    num_unit_matches = re.findall(r'(\d+\.?\d*\s*[亿万万千百吨米秒])', query)
    query_keywords.extend(num_unit_matches)

    # 提取中文词组（2个及以上连续汉字）
    chinese_matches = re.findall(r'[一-龥]{2,}', query)
    query_keywords.extend(chinese_matches)

    # 过滤掉泛词（图、表、图片等）
    stop_words = {'图', '表', '图片', '图表', '如图', '所示', '如下', '如下表', '如下图'}
    query_keywords = [kw for kw in query_keywords if kw not in stop_words]

    # 在图片描述中匹配关键词
    keyword_match_score = 0.0
    for kw in query_keywords:
        if kw in search_text or kw in section:
            keyword_match_score += 2.0

    score += min(keyword_match_score, 8.0)  # 最多加 8 分

    # 3. 整体文本相似度（字符级别）
    if search_text:
        # 检查查询的核心词是否在描述中
        query_core = re.sub(r'[图表图片如图所示]', '', query)  # 去掉泛词
        if query_core:
            overlap = len(set(query_core) & set(search_text))
            score += min(overlap * 0.2, 3.0)

    # 4. 章节匹配
    if section:
        # 从查询中提取可能的章节关键词
        section_keywords = re.findall(r'[一-龥]{2,}', query)
        for kw in section_keywords:
            if kw in section:
                score += 1.5

    # 5. 图片类型加分
    if meta.get('chunk_type') == 'chart':
        score += 2.0
    elif meta.get('chunk_type') == 'image':
        score += 1.0

    # 6. 检索相似度（如果有）
    retrieval_score = meta.get('score', 0)
    if retrieval_score > 0:
        score += min(retrieval_score * 2, 2.0)

    return score


def select_images(contexts: list, query: str) -> list:
    """
    选择要展示的图片（打分排序 + 预算控制）

    Args:
        contexts: 检索上下文列表
        query: 用户查询

    Returns:
        精选图片列表（最多 2-5 张，根据查询意图动态调整）
    """
    import re

    # 动态预算：列举型查询允许更多图片
    list_keywords = ["哪些", "有什么", "包含", "列出", "所有", "全部"]
    is_list_query = any(kw in query for kw in list_keywords)

    # 检测查询中的图片编号（如 "图2.1"）
    figure_pattern = r'图\s*(\d+\.?\d*)'
    figure_matches = re.findall(figure_pattern, query)
    has_figure_query = bool(figure_matches)

    # 新增：从检索文本中提取图表引用（见表2.2、见图2.5 等）
    # 同时记录引用所在的文件来源
    # 重要：只从语义相关的 top 5 文本块提取，避免不相关引用干扰
    referenced_figures = {}  # {图号: set(文件来源)}
    referenced_tables = {}   # {表号: set(文件来源)}

    for ctx in contexts[:5]:  # 只从前5个最相关的文本块提取引用
        doc_text = ctx.get('doc', '')
        source = ctx.get('meta', {}).get('source', '')

        # 提取 "见图X.X"、"如图X.X" 或单独的 "图X.X"
        fig_refs = re.findall(r'(?:[见如])?图\s*(\d+\.?\d*)', doc_text)
        for fig_num in fig_refs:
            if fig_num not in referenced_figures:
                referenced_figures[fig_num] = set()
            if source:
                referenced_figures[fig_num].add(source)

        # 提取 "见表X.X"、"如表X.X" 或单独的 "表X.X"
        table_refs = re.findall(r'(?:[见如])?表\s*(\d+\.?\d*)', doc_text)
        for table_num in table_refs:
            if table_num not in referenced_tables:
                referenced_tables[table_num] = set()
            if source:
                referenced_tables[table_num].add(source)

    has_referenced_figures = bool(referenced_figures or referenced_tables)

    # 获取检索结果中涉及的主要文件来源
    primary_sources = set()
    for ctx in contexts[:5]:  # 只看前5个最相关的
        source = ctx.get('meta', {}).get('source', '')
        if source:
            primary_sources.add(source)

    # 图片意图检测：区分精确查图和泛指
    strong_image_keywords = ["示意图", "流程图", "结构图", "过程线", "曲线图", "分布图", "图示", "看图", "显示图"]
    weak_image_keywords = ["图片", "图表", "如图", "图", "统计"]

    has_strong_image_intent = any(kw in query for kw in strong_image_keywords)
    has_weak_image_intent = any(kw in query for kw in weak_image_keywords)

    # 精确查图：用户指定了具体图号（如 "图2.3"），只返回最匹配的 1-2 张
    if has_figure_query:
        MAX_IMAGES = 2
        MIN_SCORE = 5.0  # 精确匹配应该高分
    # 强图片意图：明确要看某种图
    elif has_strong_image_intent:
        MAX_IMAGES = 3
        MIN_SCORE = 5.0  # 提高阈值，避免不相关图片通过
    # 列举型查询
    elif is_list_query:
        MAX_IMAGES = 5
        MIN_SCORE = 3.0
    # 有图表引用：检索文本中提到了图表
    elif has_referenced_figures:
        MAX_IMAGES = 3
        MIN_SCORE = 2.0  # 降低阈值，让引用的图表能通过
    # 弱图片意图：只是提到"图"字，可能是泛指（如 "发电量图"）
    elif has_weak_image_intent:
        MAX_IMAGES = 1  # 只返回最相关的一张
        MIN_SCORE = 2.0  # 降低阈值，让语义相关的图片能通过
    # 普通查询
    else:
        MAX_IMAGES = 2
        MIN_SCORE = 3.0

    # 获取检索结果中涉及的主要章节（只看前 3 个最相关的文本块）
    primary_sections = set()
    for ctx in contexts[:3]:
        section = ctx.get('meta', {}).get('section', '') or ctx.get('meta', {}).get('section_path', '')
        if section:
            # 提取章节编号
            # 优先匹配 X.X 格式（如 "2.3发电"），再匹配 第X章 格式
            section_num = re.search(r'(\d+\.\d+)', section)
            if not section_num:
                # 尝试匹配 "第X章" 格式
                chapter_match = re.search(r'第\s*(\d+)\s*章', section)
                if chapter_match:
                    section_num = chapter_match
            if section_num:
                primary_sections.add(section_num.group(1))

    scored_images = []
    for ctx in contexts:
        meta = ctx.get('meta', {})
        chunk_type = meta.get('chunk_type', 'text')

        # 处理图片类型和有关联图片的表格类型
        if meta.get('image_path') and chunk_type in ('image', 'chart', 'table'):
            # 传递 doc 字段（包含图片描述和上下文）
            doc = ctx.get('doc', '')
            s = score_image_relevance(query, meta, doc)

            # 图片来源
            img_source = meta.get('source', '')

            # 图片章节
            img_section = meta.get('section', '') or meta.get('section_path', '')
            # 只匹配 X.X 格式的章节号，避免匹配年份
            img_section_num = re.search(r'(\d+\.\d+)', img_section)
            img_section_id = img_section_num.group(1) if img_section_num else None

            # ========== 核心修复：图片必须与主要文本切片章节关联 ==========
            # 如果有主要章节，且图片章节不在其中，大幅降低分数
            section_penalty = 0.0
            if primary_sections and img_section_id and img_section_id not in primary_sections:
                # 图片章节与主要检索结果不匹配，惩罚
                section_penalty = -5.0  # 大幅降低分数
                # 除非图片被文本切片明确引用
                is_referenced = False
                for fig_num in referenced_figures:
                    if f"图{fig_num}" in doc or f"图 {fig_num}" in doc:
                        is_referenced = True
                        break
                if not is_referenced:
                    for table_num in referenced_tables:
                        if f"表{table_num}" in doc or f"表 {table_num}" in doc:
                            is_referenced = True
                            break
                if is_referenced:
                    section_penalty = 0.0  # 被引用则不惩罚

            s += section_penalty

            # 新增：如果图片描述中包含检索文本引用的图号，大幅加分
            # 前提：图片章节与主要检索结果的章节相关
            if referenced_figures:
                for fig_num, sources in referenced_figures.items():
                    # 只检查 doc 字段，不检查 meta（避免 section 中的误匹配）
                    if f"图{fig_num}" in doc or f"图 {fig_num}" in doc:
                        # 检查图片章节是否与主要章节匹配
                        section_match = img_section_id and img_section_id in primary_sections

                        # P2：只有章节匹配才加分，移除"s >= 5.0"漏洞
                        if section_match:
                            # 图号匹配加分
                            s += 8.0
                            # 如果图片来源与引用来源一致，额外加分
                            if img_source in sources:
                                s += 5.0  # 文件匹配额外加分
                        break

            # 新增：如果表格描述中包含检索文本引用的表号，大幅加分
            # 同样要求章节相关性
            if referenced_tables:
                for table_num, sources in referenced_tables.items():
                    # 只检查 doc 字段
                    if f"表{table_num}" in doc or f"表 {table_num}" in doc:
                        # 检查图片章节是否与主要章节匹配
                        section_match = img_section_id and img_section_id in primary_sections

                        # P2：只有章节匹配才加分，移除"s >= 5.0"漏洞
                        if section_match:
                            # 表号匹配加分
                            s += 8.0
                            # 如果图片来源与引用来源一致，额外加分
                            if img_source in sources:
                                s += 5.0  # 文件匹配额外加分
                        break

            # 新增：如果图片来源在主要检索结果中，加分
            if img_source in primary_sources:
                s += 2.0

            if s >= MIN_SCORE:
                scored_images.append({
                    'score': s,
                    'id': os.path.basename(meta['image_path']),
                    'url': f"/images/{os.path.basename(meta['image_path'])}",
                    'type': meta['chunk_type'],
                    'source': meta.get('source'),
                    'page': meta.get('page'),
                    'description': doc[:100],  # 短描述用于 UI 展示
                    'full_description': doc     # Bug 6b 修复：完整描述用于 LLM 上下文
                })

    # ========== P2：通过文本切片的 referenced_images 补充图片 ==========
    # 检查 top 5 文本切片的 referenced_images，补充未选中的关联图片
    existing_image_ids = {img['id'] for img in scored_images}

    for ctx in contexts[:5]:
        meta = ctx.get('meta', {})
        if meta.get('chunk_type') != 'text':
            continue

        referenced = meta.get('referenced_images', [])
        if not referenced:
            continue

        # 查找对应的图片切片
        for fig_num in referenced:
            # 在所有 contexts 中查找匹配的图片
            for img_ctx in contexts:
                img_meta = img_ctx.get('meta', {})
                if img_meta.get('chunk_type') not in ('image', 'chart', 'table'):
                    continue

                img_path = img_meta.get('image_path', '')
                img_id = os.path.basename(img_path)

                # 检查是否已存在
                if img_id in existing_image_ids:
                    continue

                # 检查图号/表号是否匹配
                img_doc = img_ctx.get('doc', '')
                if f"图{fig_num}" in img_doc or f"表{fig_num}" in img_doc:
                    # 添加到结果中
                    scored_images.append({
                        'score': 8.0,  # 基础分
                        'id': img_id,
                        'url': f"/images/{img_id}",
                        'type': img_meta.get('chunk_type'),
                        'source': img_meta.get('source'),
                        'page': img_meta.get('page'),
                        'description': img_doc[:100],  # 短描述用于 UI 展示
                        'full_description': img_doc     # Bug 6b 修复：完整描述用于 LLM 上下文
                    })
                    existing_image_ids.add(img_id)
                    break

    scored_images.sort(key=lambda x: x['score'], reverse=True)
    return scored_images[:MAX_IMAGES]


def _extract_rich_media(contexts: list) -> dict:
    """
    从检索结果提取富媒体信息

    Args:
        contexts: 检索上下文列表

    Returns:
        {"images": [...], "tables": [...], "sections": [...]}
    """
    images = []
    tables = []
    sections = set()

    # 白名单：只返回检索结果中存在的图片
    valid_images = set()

    for ctx in contexts:
        meta = ctx.get("meta", {})

        # 1. 独立图片切片（image_path）- 图片/图表类型的独立切片
        if meta.get("chunk_type") in ("image", "chart") and meta.get("image_path"):
            img_path = meta.get("image_path", "")
            img_id = os.path.basename(img_path)
            if img_id and img_id not in valid_images:
                valid_images.add(img_id)
                images.append({
                    "id": img_id,
                    "url": f"/images/{img_id}",
                    "type": meta.get("chunk_type"),
                    "source": meta.get("source"),
                    "page": meta.get("page"),
                    "order": 0  # 独立图片默认 order=0
                })

        # 2. 关联图片（images 字段）- 表格/段落中嵌入的图片
        # 统一格式：images = [{"id": "abc.jpg", "order": 1}, ...]
        img_list = None
        if meta.get("images"):
            img_list = meta["images"]
            # 兼容 JSON 字符串格式
            if isinstance(img_list, str):
                try:
                    img_list = json.loads(img_list)
                except (json.JSONDecodeError, TypeError):
                    img_list = []
        elif meta.get("images_json"):
            # 兼容旧格式 images_json
            try:
                img_list = json.loads(meta["images_json"])
            except (json.JSONDecodeError, TypeError):
                img_list = []

        if img_list and isinstance(img_list, list):
            for img_info in img_list:
                # 兼容两种格式：{"id": "xxx", "order": 1} 或直接字符串
                if isinstance(img_info, dict):
                    img_id = img_info.get("id") or img_info.get("path", "")
                    order = img_info.get("order", 0)
                else:
                    img_id = str(img_info)
                    order = 0

                if img_id and img_id not in valid_images:
                    valid_images.add(img_id)
                    images.append({
                        "id": img_id,
                        "url": f"/images/{img_id}",
                        "type": "associated",  # 关联图片
                        "source": meta.get("source"),
                        "page": meta.get("page"),
                        "order": order
                    })

        # 3. 表格切片本身有 image_path（表格作为图片存储）
        if meta.get("chunk_type") == "table" and meta.get("image_path"):
            img_path = meta.get("image_path", "")
            img_id = os.path.basename(img_path)
            if img_id and img_id not in valid_images:
                valid_images.add(img_id)
                images.append({
                    "id": img_id,
                    "url": f"/images/{img_id}",
                    "type": "table_image",
                    "source": meta.get("source"),
                    "page": meta.get("page"),
                    "order": 0
                })

        # 提取表格
        if meta.get("is_table") or meta.get("chunk_type") == "table":
            tables.append({
                "id": meta.get("id", ""),
                "markdown": ctx.get("doc", "")[:1000],  # 截取部分
                "page": meta.get("page"),
                "source": meta.get("source")
            })

        # 提取章节
        if meta.get("section_path"):
            sections.add(meta["section_path"])

    # 按 order 排序
    images.sort(key=lambda x: x.get("order", 0))

    return {
        "images": images,
        "tables": tables,
        "sections": list(sections)
    }


def chat_with_llm(message: str, history: list = None, enable_web_search: bool = True) -> dict:
    """
    普通聊天 - 使用LLM直接回复

    Args:
        message: 用户消息
        history: 对话历史（由后端传入）
        enable_web_search: 是否启用网络搜索

    Returns:
        {"answer": str, "sources": list, "web_searched": bool}
    """
    from config import get_llm_client

    client = get_llm_client()

    # 构建消息
    messages = []

    # 添加历史
    if history:
        for h in history[-10:]:  # 最多10轮历史
            messages.append({"role": h["role"], "content": h["content"]})

    messages.append({"role": "user", "content": message})

    # 调用 LLM
    response = client.chat.completions.create(
        model=RAG_CHAT_MODEL,
        messages=messages,
        max_tokens=2048
    )

    answer = response.choices[0].message.content

    return {
        "answer": answer,
        "sources": [],
        "web_searched": False
    }


def reciprocal_rank_fusion(results_list, weights=None, k=60):
    """
    倒数排名融合算法

    Args:
        results_list: 多个检索结果列表
        weights: 各结果权重
        k: RRF 参数

    Returns:
        融合后的排序结果
    """
    if weights is None:
        weights = [1.0] * len(results_list)

    fused_scores = {}
    doc_data = {}

    for results, weight in zip(results_list, weights):
        if not results or not results.get('ids'):
            continue

        ids = results['ids'][0]
        docs = results['documents'][0] if results.get('documents') else [''] * len(ids)
        metas = results['metadatas'][0] if results.get('metadatas') else [{}] * len(ids)
        distances = results['distances'][0] if results.get('distances') else [0] * len(ids)

        for rank, (doc_id, doc, meta, dist) in enumerate(zip(ids, docs, metas, distances)):
            if doc_id not in fused_scores:
                fused_scores[doc_id] = 0
                doc_data[doc_id] = {'doc': doc, 'meta': meta, 'dist': dist}

            # RRF 分数
            fused_scores[doc_id] += weight / (rank + k)

    # 按分数排序
    sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)

    return {
        'ids': sorted_ids,
        'documents': [doc_data[i]['doc'] for i in sorted_ids],
        'metadatas': [doc_data[i]['meta'] for i in sorted_ids],
        'scores': [fused_scores[i] for i in sorted_ids],
        'distances': [doc_data[i]['dist'] for i in sorted_ids]
    }


def search_hybrid(query: str, top_k: int = 5, candidates: int = 15,
                  allowed_levels: list = None, allowed_collections: list = None):
    """
    混合检索：直接调用生产环境引擎，确保测试效果与生产一致

    Args:
        query: 查询文本
        top_k: 返回数量
        candidates: 候选数量（用于 RERANK_CANDIDATES，由 config 控制）
        allowed_levels: 允许的安全级别
        allowed_collections: 允许的向量库列表

    Returns:
        融合后的检索结果
    """
    from core.engine import get_engine

    engine = get_engine()

    # 直接调用生产环境的检索方法
    result = engine.search_knowledge(
        query=query,
        top_k=top_k,
        allowed_levels=allowed_levels,
        collections=allowed_collections
    )

    # 添加 scores 字段（用于前端显示）
    if result and result.get('ids') and result['ids'][0]:
        distances = result.get('distances', [[]])[0]
        # 将距离转换为相似度分数（距离越小，分数越高）
        scores = [1.0 - d if d <= 1.0 else 1.0 / (1.0 + d) for d in distances]
        result['scores'] = [scores]
    else:
        result = {
            'ids': [[]],
            'documents': [[]],
            'metadatas': [[]],
            'distances': [[]],
            'scores': [[]]
        }

    return result


# ==================== 路由 ====================

@chat_bp.route('/chat', methods=['POST'])
@require_gateway_auth
def chat():
    """
    普通聊天模式 - 直接使用LLM回复

    请求体:
    {
        "message": "消息内容",
        "history": [{"role": "user/assistant", "content": "..."}]  // 可选
    }
    """
    data = request.json or {}
    message = data.get('message')
    history = data.get('history', [])

    if not message:
        return jsonify({"error": "缺少 message"}), 400

    # 输入安全验证
    is_valid, reason = validate_query(message)
    if not is_valid:
        return jsonify({"error": reason}), 400

    # 智能聊天
    result = chat_with_llm(message, history)

    # 过滤敏感信息
    answer = filter_response(result["answer"])

    return jsonify({
        "answer": answer,
        "mode": "chat",
        "sources": result.get("sources", []),
        "web_searched": result.get("web_searched", False)
    })


@chat_bp.route('/rag', methods=['POST'])
@require_gateway_auth
def rag():
    """
    知识库问答模式 - SSE 流式返回

    请求体:
    {
        "message": "消息内容",
        "history": [{"role": "user/assistant", "content": "..."}],  // 可选（开发环境）
        "chat_history": [{"role": "user/assistant", "content": "..."}],  // 可选（生产环境）
        "collections": ["public_kb"],  // 可选，知识库列表
        "session_id": "xxx"  // 可选，会话ID
    }

    SSE 事件序列:
    1. start: 开始处理
    2. sources: 检索到的来源
    3. chunk: 每个 token
    4. finish: 完成响应（包含完整 answer 和 sources）
    5. error: 错误事件
    """
    from config import IS_PROD, ENABLE_SESSION

    data = request.json or {}

    message = data.get('message')
    # 兼容两种参数名：history（旧）和 chat_history（新）
    history = data.get('history') or data.get('chat_history')
    collections = data.get('collections')
    session_id = data.get('session_id')

    if not message:
        return jsonify({"error": "缺少 message"}), 400

    # 生产环境强制校验 chat_history
    if IS_PROD and history is None:
        return jsonify({
            "error": "chat_history is required in production",
            "code": "MISSING_HISTORY"
        }), 400

    # 输入安全验证
    is_valid, reason = validate_query(message)
    if not is_valid:
        return jsonify({"error": reason}), 400

    # 如果没有指定 collections，使用默认的公开库
    if not collections:
        collections = ['public_kb']

    # ==================== 会话历史加载 ====================
    # 优先使用传入的 history，否则从 session_repo 加载
    user_id = request.current_user.get("user_id")

    if history is not None:
        # 使用传入的历史（生产环境必须传入）
        pass
    elif session_id and ENABLE_SESSION:
        # 开发环境：从本地数据库加载
        try:
            session_repo = current_app.session_repo
            history = session_repo.get_history(session_id)
            # 限制历史长度
            history = history[-10:] if len(history) > 10 else history
        except Exception:
            history = []
    else:
        history = []

    # 如果没有 session_id，创建新会话（仅开发环境）
    if not session_id and ENABLE_SESSION:
        try:
            session_repo = current_app.session_repo
            session_id = session_repo.create_session(user_id)
        except Exception:
            pass  # 创建失败不影响主流程

    # 提前获取 session_repo 引用，避免在生成器内部访问 current_app
    # （生成器执行时应用上下文可能已结束）
    session_repo_ref = None
    if ENABLE_SESSION:
        try:
            session_repo_ref = current_app.session_repo
        except Exception:
            pass

    def generate():
        """生成 SSE 流"""
        start_time = _time.time()
        full_answer = []

        try:
            # 0. 意图分析（改写 + 双层判断）
            context_images = []
            if history:
                # 从历史中提取图片信息
                for msg in reversed(history[-4:]):  # 最近2轮
                    metadata = msg.get("metadata", {})
                    if isinstance(metadata, dict):
                        images = metadata.get("images", [])
                        if images:
                            context_images.extend(images[:3])

            try:
                from core.intent_analyzer import analyze_intent
                intent = analyze_intent(message, history or [], context_images)

                import logging
                logging.info(f"[意图分析] use_context={intent.use_context}, need_retrieval={intent.need_retrieval}, reason={intent.reason}")

                # 如果不需要检索，直接使用上下文回答
                if not intent.need_retrieval and intent.use_context:
                    yield f"data: {json.dumps({'type': 'start', 'message': '正在分析...'}, ensure_ascii=False)}\n\n"

                    # 构建上下文
                    context_text = ""
                    if history:
                        # 提取最近的助手回答
                        for msg in reversed(history):
                            if msg.get("role") == "assistant":
                                context_text = msg.get("content", "")
                                break

                    # 构建图片上下文
                    image_context = ""
                    if context_images:
                        image_context = "\n\n【上下文中的图片】\n"
                        for img in context_images[:5]:
                            if isinstance(img, dict):
                                desc = img.get("description", "")
                                img_type = img.get("type", "图片")
                                image_context += f"- {img_type}: {desc}\n"

                    # 直接调用 LLM
                    from config import get_llm_client, DASHSCOPE_MODEL
                    client = get_llm_client()

                    system_prompt = f"""你是一个专业的知识库问答助手。请根据对话历史和上下文回答用户问题。

如果用户问题是关于图片的，请根据上下文中的图片描述进行分析。

{image_context}"""

                    user_prompt = f"""对话历史：
{context_text[:2000] if context_text else '（无历史上下文）'}

用户问题：{intent.rewritten_query}

请直接回答用户问题。"""

                    # 流式生成回答
                    for token in client.chat.completions.create(
                        model=DASHSCOPE_MODEL,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.7,
                        stream=True
                    ):
                        if token.choices and token.choices[0].delta.content:
                            content = token.choices[0].delta.content
                            full_answer.append(content)
                            yield f"data: {json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)}\n\n"

                    # 发送完成事件
                    yield f"data: {json.dumps({'type': 'finish', 'answer': ''.join(full_answer), 'sources': []}, ensure_ascii=False)}\n\n"
                    return  # 直接返回，不执行后续检索

            except Exception as e:
                import logging
                logging.warning(f"意图分析失败: {e}，继续执行检索流程")

            # 1. 发送开始事件
            yield f"data: {json.dumps({'type': 'start', 'message': '正在检索知识库...'}, ensure_ascii=False)}\n\n"

            # 2. 执行混合检索（扩大召回数量，确保图片切片有机会被召回）
            search_result = search_hybrid(
                message,
                top_k=15,  # 扩大返回数量
                candidates=100,  # 大幅扩大候选池，让图片切片有机会被召回
                allowed_collections=collections
            )

            # 提取上下文
            contexts = []
            sources = []

            if search_result.get('documents') and search_result['documents'][0]:
                docs = search_result['documents'][0]
                metas = search_result.get('metadatas', [[]])[0]
                scores = search_result.get('scores', [[]])[0]

                # 图片相关性提升：检测图片编号或强意图
                import re
                figure_pattern = r'图\s*(\d+\.?\d*)'
                figure_matches = re.findall(figure_pattern, message)
                has_figure_query = bool(figure_matches)

                # Bug 4 修复：缩小 strong_image_keywords，移除歧义词
                # "过程线" 是水文术语不是图片意图，"图片"/"图表"/"如图" 太泛
                strong_image_keywords = ["示意图", "流程图", "结构图", "曲线图", "分布图", "图示", "看图", "显示图", "给我看"]
                has_image_intent = has_figure_query or any(kw in message for kw in strong_image_keywords)

                # Bug 2 修复：不重排 contexts，只在 meta 里打标记给后续的 select_images 用
                if has_image_intent:
                    for i, (doc, meta, score) in enumerate(zip(docs, metas, scores)):
                        if meta.get('chunk_type') in ('image', 'chart'):
                            # 检查 caption 是否与查询相关
                            caption = meta.get('caption', '') or ''
                            should_boost = False
                            boost_factor = 1.0

                            # 如果查询包含图片编号，检查 caption 是否匹配
                            if has_figure_query:
                                for fig_num in figure_matches:
                                    if f"图{fig_num}" in caption or f"图 {fig_num}" in caption:
                                        should_boost = True
                                        boost_factor = 2.0  # 强提升
                                        break

                            # 或者 caption 与查询有足够重叠
                            if not should_boost:
                                overlap = len(set(message) & set(caption))
                                if overlap >= 3 or any(word in caption for word in message if len(word) >= 3):
                                    should_boost = True
                                    boost_factor = 1.5  # 提升 50%

                            if should_boost:
                                meta['_image_boost'] = boost_factor  # 打标记，不重排
                    # 不做 sort！保持检索引擎的原始排序

                # 按 source 去重，保留最高分
                seen_sources = {}
                for doc, meta, score in zip(docs, metas, scores):
                    source_name = meta.get('source', '未知')
                    if source_name not in seen_sources or score > seen_sources[source_name]['score']:
                        page = meta.get('page', 0)
                        page_end = meta.get('page_end')
                        # 构建页码范围显示
                        if page_end and page_end > page:
                            page_range = f"{page}-{page_end}"
                        else:
                            page_range = str(page)

                        seen_sources[source_name] = {
                            'source': source_name,
                            'page': page,
                            'page_end': page_end,
                            'page_range': page_range,
                            'section': meta.get('section', '') or meta.get('section_path', ''),
                            'chunk_type': meta.get('chunk_type', 'text'),
                            'doc_type': meta.get('doc_type', 'other'),  # 文档类型
                            'section_chunk_id': meta.get('section_chunk_id'),  # 章节内序号
                            'score': round(score, 3) if isinstance(score, float) else score
                        }
                    # ========== P1：图片使用 full_description ==========
                    # 图片切片使用完整描述（用于 LLM 上下文），而非短摘要
                    display_doc = doc
                    if meta.get('chunk_type') in ('image', 'chart', 'table'):
                        full_desc = meta.get('full_description', '')
                        if full_desc:
                            display_doc = full_desc

                    # contexts 仍然保留所有结果用于生成答案
                    contexts.append({'doc': display_doc, 'meta': meta})

                sources = list(seen_sources.values())

                # 补充检索：从文本切片中提取图号/表号引用，补充检索对应的图片
                # 重要：只从最相关的 top 5 文本切片提取引用，避免不相关引用干扰
                import re
                referenced_figures = set()
                referenced_tables = set()

                # 只检查 top 5 文本切片（与 select_images 逻辑一致）
                text_contexts = [ctx for ctx in contexts if ctx.get('meta', {}).get('chunk_type') == 'text'][:5]
                for ctx in text_contexts:
                    doc_text = ctx.get('doc', '')
                    fig_refs = re.findall(r'(?:[见如及和与])?图\s*(\d+\.?\d*)', doc_text)
                    referenced_figures.update(fig_refs)
                    table_refs = re.findall(r'(?:[见如及和与])?表\s*(\d+\.?\d*)', doc_text)
                    referenced_tables.update(table_refs)

                # 检查哪些图号/表号对应的图片不在 contexts 中
                existing_figure_images = set()
                existing_table_images = set()
                for ctx in contexts:
                    doc = ctx.get('doc', '')
                    meta = ctx.get('meta', {})
                    if meta.get('chunk_type') in ('image', 'chart'):
                        for fig_num in referenced_figures:
                            if f"图{fig_num}" in doc:
                                existing_figure_images.add(fig_num)
                        for table_num in referenced_tables:
                            if f"表{table_num}" in doc:
                                existing_table_images.add(table_num)

                # 需要补充检索的图号/表号
                missing_figures = referenced_figures - existing_figure_images
                missing_tables = referenced_tables - existing_table_images

                # 计算主要章节（用于补充检索过滤）
                primary_sections_for_supplement = set()
                for ctx in text_contexts[:3]:
                    section = ctx.get('meta', {}).get('section', '') or ctx.get('meta', {}).get('section_path', '')
                    if section:
                        section_num = re.search(r'(\d+\.\d+)', section)
                        if not section_num:
                            chapter_match = re.search(r'第\s*(\d+)\s*章', section)
                            if chapter_match:
                                section_num = chapter_match
                        if section_num:
                            primary_sections_for_supplement.add(section_num.group(1))

                if missing_figures or missing_tables:
                    # 补充检索
                    from knowledge.manager import get_kb_manager
                    kb_manager = get_kb_manager()
                    kb_name = collections[0] if collections else 'public_kb'
                    collection = kb_manager.get_collection(kb_name)

                    if collection:
                        # 构建补充查询
                        supplement_queries = []
                        for fig_num in missing_figures:
                            supplement_queries.append(f"图{fig_num}")
                        for table_num in missing_tables:
                            supplement_queries.append(f"表{table_num}")

                        supplement_query = " ".join(supplement_queries)

                        # 使用 embedding 检索
                        # P4：复用 engine 的 embedding 模型，避免重复加载
                        try:
                            from core.engine import get_engine
                            engine = get_engine()
                            query_vector = engine.embedding_model.encode(supplement_query).tolist()
                            if isinstance(query_vector[0], list):
                                query_vector = query_vector[0]

                            supplement_result = collection.query(
                                query_embeddings=[query_vector],
                                n_results=10,
                                include=['documents', 'metadatas', 'distances']
                            )

                            # 添加匹配的图片切片
                            for supp_doc, supp_meta, supp_dist in zip(
                                supplement_result['documents'][0],
                                supplement_result['metadatas'][0],
                                supplement_result['distances'][0]
                            ):
                                chunk_type = supp_meta.get('chunk_type', '')
                                if chunk_type in ('image', 'chart'):
                                    # 检查是否匹配缺失的图号/表号
                                    is_match = False
                                    matched_fig = None
                                    for fig_num in missing_figures:
                                        if f"图{fig_num}" in supp_doc:
                                            is_match = True
                                            matched_fig = fig_num
                                            break
                                    for table_num in missing_tables:
                                        if f"表{table_num}" in supp_doc:
                                            is_match = True
                                            break

                                    if is_match:
                                        # 额外检查：图片章节是否与主要章节匹配
                                        # 避免补充检索到不相关的图片
                                        supp_section = supp_meta.get('section', '') or supp_meta.get('section_path', '')
                                        supp_section_num = re.search(r'(\d+\.\d+)', supp_section)
                                        supp_section_id = supp_section_num.group(1) if supp_section_num else None

                                        # 如果图片章节不在主要章节中，跳过
                                        if primary_sections_for_supplement and supp_section_id and supp_section_id not in primary_sections_for_supplement:
                                            # 不是主要章节的图片，跳过
                                            continue

                                        # Bug 6a 修复：补充检索的图片也要做 full_description 替换
                                        # 与正常检索保持一致
                                        display_doc = supp_doc
                                        if supp_meta.get('chunk_type') in ('image', 'chart', 'table'):
                                            full_desc = supp_meta.get('full_description', '')
                                            if full_desc:
                                                display_doc = full_desc

                                        contexts.append({
                                            'doc': display_doc,
                                            'meta': supp_meta,
                                            'score': 1.0 - supp_dist
                                        })
                                        import logging
                                        logging.info(f"[补充检索] 添加图片: {supp_meta.get('image_path', '')}")
                        except Exception as e:
                            import logging
                            logging.warning(f"补充检索失败: {e}")

            # 发送来源事件
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources[:5]}, ensure_ascii=False)}\n\n"

            # 调试：检查 contexts 中是否有图片切片
            image_count = sum(1 for ctx in contexts if ctx.get('meta', {}).get('chunk_type') in ('image', 'chart'))
            if image_count > 0:
                import logging
                logging.info(f"[图片检索] contexts 中包含 {image_count} 个图片/图表切片")
                for ctx in contexts:
                    meta = ctx.get('meta', {})
                    if meta.get('chunk_type') in ('image', 'chart'):
                        logging.info(f"  - 图片: {meta.get('caption', '')[:50]}, path: {meta.get('image_path', '')}")

            # 2.5. 懒加载增强（Phase 4）
            # 暂时禁用：VLM 调用耗时过长，可能导致请求超时
            # TODO: 后续可改为异步后台任务
            try:
                import asyncio
                from knowledge.lazy_enhance import enhance_retrieved_chunks
                kb_name = collections[0] if collections else 'public_kb'
                asyncio.run(enhance_retrieved_chunks(contexts, message, kb_name))
            except Exception as e:
                import logging
                logging.warning(f"懒加载增强失败: {e}")

            # 3. 选择要展示的图片（Phase 5）
            selected_images = select_images(contexts, message)

            # 4. 构建 prompt（Phase 6：LLM 图片感知）
            # Bug 1 修复：文本切片用于 top 5 名额竞争，图片描述不参与竞争
            text_contexts = [ctx for ctx in contexts if ctx.get('meta', {}).get('chunk_type') not in ('image', 'chart', 'table')]
            context_text = "\n\n".join([ctx.get('doc', '') for ctx in text_contexts[:5]])

            # Bug 6b 优化：直接使用 selected_images 中的 full_description
            # 这样 LLM 既能看到文本切片，也能知道图片内容
            if selected_images:
                image_descriptions = []
                for i, img in enumerate(selected_images, 1):
                    # 直接使用 select_images 时带上的 full_description
                    full_desc = img.get('full_description', '') or img.get('description', '')
                    if full_desc:
                        image_descriptions.append(f"【图片{i}】{full_desc}")
                if image_descriptions:
                    context_text += "\n\n【相关图片信息】\n" + "\n\n".join(image_descriptions)

            enhanced_context = context_text

            # 5. 流式生成回答
            from core.engine import get_engine
            engine = get_engine()

            for token in engine.generate_answer_stream(message, enhanced_context, history):
                full_answer.append(token)
                yield f"data: {json.dumps({'type': 'chunk', 'content': token}, ensure_ascii=False)}\n\n"

            # 6. P0：答案对齐过滤器
            # 从 LLM 回答中提取图号引用，过滤图片选择结果
            full_answer_text = "".join(full_answer)

            # 提取回答中引用的图号/表号
            mentioned = set()
            # 中文图号：图2.1、图 2-1、见图2.1 等
            mentioned.update(re.findall(r'(?:[见如])?图\s*(\d+[\.\-]?\d*)', full_answer_text))
            # 中文表号：表2.1、表 2-1、见表2.1 等
            mentioned.update(re.findall(r'(?:[见如])?表\s*(\d+[\.\-]?\d*)', full_answer_text))
            # 英文图号：Figure 2.1、Fig.2.1 等
            mentioned.update(re.findall(r'(?:Fig(?:ure)?\.?\s*)(\d+[\.\-]?\d*)', full_answer_text, re.I))

            # 根据回答中的引用过滤图片
            if mentioned:
                aligned_images = []
                for img in selected_images:
                    desc = img.get('description', '')
                    # 标准化图号格式（将连字符转为点）
                    for ref in mentioned:
                        ref_normalized = ref.replace('-', '.')
                        if (f"图{ref_normalized}" in desc or
                            f"表{ref_normalized}" in desc or
                            f"图 {ref_normalized}" in desc or
                            f"表 {ref_normalized}" in desc):
                            aligned_images.append(img)
                            break
                # 如果有匹配的图片，使用对齐后的结果
                if aligned_images:
                    selected_images = aligned_images
                else:
                    # 没有匹配到，保留 1 张（可能是正则未覆盖的情况）
                    selected_images = selected_images[:1]
            else:
                # LLM 没有提图号，只保留得分最高的 1 张
                selected_images = selected_images[:1]

            rich_media = {'images': selected_images, 'tables': [], 'sections': []}

            # 7. 保存消息到会话（仅开发环境）
            if session_id and session_repo_ref:
                try:
                    # 保存用户消息
                    session_repo_ref.add_message(session_id, 'user', message)
                    # 保存 AI 回答（包含 metadata：图片、来源等）
                    assistant_metadata = {}
                    if rich_media.get('images'):
                        assistant_metadata['images'] = rich_media['images']
                    if sources:
                        assistant_metadata['sources'] = sources
                    session_repo_ref.add_message(session_id, 'assistant', full_answer_text, assistant_metadata if assistant_metadata else None)
                    # 更新会话最后活跃时间
                    if hasattr(session_repo_ref, 'update_last_active'):
                        session_repo_ref.update_last_active(session_id)
                except Exception as e:
                    import logging
                    logging.warning(f"保存会话消息失败: {e}")

            # 8. 添加引用标注（自动插入 [ref:chunk_id]）
            citation_result = _attach_citations(full_answer_text, contexts)

            # 9. 过滤敏感信息（违禁词等）
            filtered_answer = filter_response(citation_result.get("answer_with_refs", full_answer_text))

            # 10. 发送完成事件
            duration_ms = int((_time.time() - start_time) * 1000)
            finish_event = {
                "type": "finish",
                "answer": filtered_answer,
                "mode": "rag",
                "session_id": session_id,
                "sources": sources,
                "citations": citation_result.get("citations", []),  # 结构化引用列表
                "images": rich_media["images"],
                "tables": rich_media["tables"],
                "sections": rich_media["sections"],
                "duration_ms": duration_ms
            }
            yield f"data: {json.dumps(finish_event, ensure_ascii=False)}\n\n"

        except Exception as e:
            import traceback
            error_event = {
                "type": "error",
                "message": str(e),
                "traceback": traceback.format_exc()
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@chat_bp.route('/search', methods=['POST'])
@require_gateway_auth
def search():
    """
    混合检索接口 - 供 Dify 工作流调用

    请求体:
    {
        "query": "查询文本",
        "top_k": 5,
        "collections": ["public_kb"]  // 可选
    }
    """
    data = request.json or {}
    query = data.get('query', '')
    top_k = data.get('top_k', 5)
    collections = data.get('collections')  # 后端传入的知识库列表

    if not query:
        return jsonify({'error': 'query is required'}), 400

    # 如果没有指定 collections，使用默认的公开库
    if not collections:
        collections = ['public_kb']

    results = search_hybrid(query, top_k=top_k, allowed_collections=collections)

    return jsonify({
        'contexts': results['documents'][0],
        'metadatas': results['metadatas'][0],
        'scores': results['distances'][0]
    })
