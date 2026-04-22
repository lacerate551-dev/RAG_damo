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


def score_image_relevance(query: str, meta: dict) -> float:
    """
    图片相关性打分（Phase 5）

    Args:
        query: 用户查询
        meta: 切片元数据

    Returns:
        相关性分数（>= 3.0 推荐展示）
    """
    score = 0.0

    # 1. 查询意图匹配（最重要）
    intent_keywords = ["结构", "流程", "图", "示意", "图表", "展示", "架构", "拓扑", "图示"]
    if any(kw in query for kw in intent_keywords):
        score += 3.0

    # 2. 图片类型
    if meta.get('chunk_type') == 'chart':
        score += 2.0
    elif meta.get('chunk_type') == 'image':
        score += 1.0

    # 3. 相似度
    score += min(meta.get('score', 0), 1.0)

    return score


def select_images(contexts: list, query: str) -> list:
    """
    选择要展示的图片（打分排序 + 预算控制）（Phase 5）

    Args:
        contexts: 检索上下文列表
        query: 用户查询

    Returns:
        精选图片列表（最多 2-5 张，根据查询意图动态调整）
    """
    # 动态预算：列举型查询允许更多图片
    list_keywords = ["哪些", "有什么", "包含", "列出", "所有", "全部"]
    is_list_query = any(kw in query for kw in list_keywords)

    MAX_IMAGES = 5 if is_list_query else 2
    MIN_SCORE = 2.5  # 降低阈值，避免过滤掉相关图片

    scored_images = []
    for ctx in contexts:
        meta = ctx.get('meta', {})
        if meta.get('chunk_type') in ('image', 'chart') and meta.get('image_path'):
            s = score_image_relevance(query, meta)
            if s >= MIN_SCORE:
                scored_images.append({
                    'score': s,
                    'id': os.path.basename(meta['image_path']),
                    'url': f"/images/{os.path.basename(meta['image_path'])}",
                    'type': meta['chunk_type'],
                    'source': meta.get('source'),
                    'page': meta.get('page'),
                    'description': ctx.get('doc', '')[:100]
                })

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
            # 1. 发送开始事件
            yield f"data: {json.dumps({'type': 'start', 'message': '正在检索知识库...'}, ensure_ascii=False)}\n\n"

            # 2. 执行混合检索
            search_result = search_hybrid(
                message,
                top_k=5,
                candidates=15,
                allowed_collections=collections
            )

            # 提取上下文
            contexts = []
            sources = []

            if search_result.get('documents') and search_result['documents'][0]:
                docs = search_result['documents'][0]
                metas = search_result.get('metadatas', [[]])[0]
                scores = search_result.get('scores', [[]])[0]

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
                    # contexts 仍然保留所有结果用于生成答案
                    contexts.append({'doc': doc, 'meta': meta})

                sources = list(seen_sources.values())

            # 发送来源事件
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources[:5]}, ensure_ascii=False)}\n\n"

            # 2.5. 懒加载增强（Phase 4）
            # 对检索命中的图片/表格按需调用 VLM/LLM
            try:
                import asyncio
                from knowledge.lazy_enhance import enhance_retrieved_chunks

                # 获取知识库名称（取第一个）
                kb_name = collections[0] if collections else 'public_kb'

                # 异步增强检索结果
                asyncio.run(enhance_retrieved_chunks(contexts, message, kb_name))
            except Exception as e:
                import logging
                logging.warning(f"懒加载增强失败: {e}")

            # 3. 选择要展示的图片（Phase 5）
            selected_images = select_images(contexts, message)

            # 4. 构建 prompt（Phase 6：LLM 图片感知）
            context_text = "\n\n".join([ctx.get('doc', '') for ctx in contexts[:5]])

            # 添加图片信息到 prompt
            image_info = ""
            if selected_images:
                image_info = "\n\n【可用图片】\n你可以使用以下图片辅助回答：\n"
                for i, img in enumerate(selected_images, 1):
                    image_info += f"[图片{i}] {img['description']}\n"
                image_info += "\n如果图片有助于理解，请在回答中提及（如：如下图所示）。\n"

            enhanced_context = context_text + image_info

            # 5. 流式生成回答
            from core.engine import get_engine
            engine = get_engine()

            for token in engine.generate_answer_stream(message, enhanced_context, history):
                full_answer.append(token)
                yield f"data: {json.dumps({'type': 'chunk', 'content': token}, ensure_ascii=False)}\n\n"

            # 6. 提取富媒体信息（使用精选图片）
            rich_media = _extract_rich_media(contexts)
            # 替换为精选图片
            if selected_images:
                rich_media['images'] = selected_images

            # 7. 保存消息到会话（仅开发环境）
            full_answer_text = "".join(full_answer)
            if session_id and session_repo_ref:
                try:
                    # 保存用户消息
                    session_repo_ref.add_message(session_id, 'user', message)
                    # 保存 AI 回答
                    session_repo_ref.add_message(session_id, 'assistant', full_answer_text)
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
