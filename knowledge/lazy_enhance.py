"""
懒加载增强模块（Phase 4）

按需调用 LLM/VLM 生成表格摘要和图片描述
"""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 缓存目录（扁平化）
VLM_CACHE_DIR = Path(".data/cache/vlm")
LLM_CACHE_DIR = Path(".data/cache/llm")


def compute_file_hash(file_path: str) -> str:
    """计算文件哈希"""
    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.warning(f"计算文件哈希失败: {e}")
        return hashlib.md5(file_path.encode()).hexdigest()


async def lazy_vlm_description(chunk_id: str, image_path: str, kb_name: str, metadata: dict = None) -> str:
    """
    懒加载 VLM 描述

    触发条件：图片切片被检索命中

    Args:
        chunk_id: 切片 ID
        image_path: 图片路径（相对路径或绝对路径）
        kb_name: 知识库名称
        metadata: 图片元数据（包含 section、page、caption、上下文等）

    Returns:
        VLM 生成的图片描述
    """
    import os
    from knowledge.manager import get_kb_manager

    # 构建完整图片路径
    if not os.path.isabs(image_path):
        full_image_path = os.path.join('.data/images', image_path)
    else:
        full_image_path = image_path

    # 1. 检查缓存
    img_hash = compute_file_hash(full_image_path)
    cache_file = VLM_CACHE_DIR / f"{img_hash}.txt"
    if cache_file.exists():
        logger.info(f"VLM 缓存命中: {image_path}")
        return cache_file.read_text(encoding='utf-8')

    # 2. 调用 VLM（传入元数据）
    logger.info(f"VLM 懒加载: {image_path}")
    kb_manager = get_kb_manager()
    description = kb_manager._generate_image_description(full_image_path, metadata=metadata)

    # 3. 写入缓存
    VLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(description, encoding='utf-8')

    # 4. 更新向量库（metadata + embedding）
    try:
        collection = kb_manager.get_collection(kb_name)
        result = collection.get(ids=[chunk_id], include=['metadatas'])
        if result['metadatas']:
            # 更新 metadata
            new_metadata = {
                **result['metadatas'][0],
                'has_vlm_desc': True,
                'vlm_desc': description
            }

            # 更新 embedding（使用 VLM 描述重新计算向量）
            # 这样 VLM 描述中的关键词（如"发电量"）才能参与相似度检索
            embedding_model = kb_manager.embedding_model
            if embedding_model:
                new_vector = embedding_model.encode(description).tolist()
                if isinstance(new_vector[0], list):
                    new_vector = new_vector[0]

                collection.update(
                    ids=[chunk_id],
                    metadatas=[new_metadata],
                    embeddings=[new_vector],
                    documents=[description]  # 同时更新 document 字段
                )
                logger.info(f"已更新向量库 embedding: {chunk_id}")
            else:
                # 无 embedding 模型时只更新 metadata
                collection.update(
                    ids=[chunk_id],
                    metadatas=[new_metadata]
                )
    except Exception as e:
        logger.warning(f"更新向量库失败: {e}")

    return description


async def lazy_table_summary(chunk_id: str, table_md: str, kb_name: str) -> str:
    """
    懒加载表格摘要

    触发条件：表格切片被检索命中且相关性 > 0.7

    Args:
        chunk_id: 切片 ID
        table_md: 表格 Markdown 内容
        kb_name: 知识库名称

    Returns:
        LLM 生成的表格摘要
    """
    from knowledge.manager import get_kb_manager

    # 1. 检查缓存
    table_hash = hashlib.md5(table_md.encode()).hexdigest()
    cache_file = LLM_CACHE_DIR / f"{table_hash}.txt"
    if cache_file.exists():
        logger.info(f"LLM 缓存命中: {chunk_id}")
        return cache_file.read_text(encoding='utf-8')

    # 2. 调用 LLM
    logger.info(f"LLM 懒加载: {chunk_id}")
    kb_manager = get_kb_manager()
    summary = kb_manager._generate_table_summary(table_md, None)

    # 3. 写入缓存
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(summary, encoding='utf-8')

    # 4. 更新向量库（可选）
    try:
        collection = kb_manager.get_collection(kb_name)
        result = collection.get(ids=[chunk_id], include=['metadatas'])
        if result['metadatas']:
            # 新增摘要切片
            embedding_model = kb_manager.embedding_model
            vector = embedding_model.encode(summary).tolist()
            if isinstance(vector[0], list):
                vector = vector[0]

            collection.add(
                ids=[f"{chunk_id}_summary"],
                embeddings=[vector],
                documents=[summary],
                metadatas=[{
                    **result['metadatas'][0],
                    'is_summary': True,
                    'original_doc_id': chunk_id
                }]
            )
            # 更新原切片标记
            collection.update(
                ids=[chunk_id],
                metadatas=[{**result['metadatas'][0], 'has_summary': True}]
            )
    except Exception as e:
        logger.warning(f"更新向量库失败: {e}")

    return summary


async def enhance_retrieved_chunks(contexts: list, query: str, kb_name: str):
    """
    检索后增强：按需调用 LLM/VLM

    Args:
        contexts: 检索上下文列表
        query: 用户查询
        kb_name: 知识库名称
    """
    for ctx in contexts:
        meta = ctx.get('meta', {})
        chunk_type = meta.get('chunk_type', 'text')
        image_path = meta.get('image_path', '')

        # 图片切片：懒加载 VLM 描述
        if chunk_type in ('image', 'chart') and not meta.get('has_vlm_desc'):
            if image_path:
                try:
                    # 从 doc 字段中提取图号（上下文可能包含"见图2.5"等）
                    doc_text = ctx.get('doc', '')
                    import re

                    # 提取图号（从前文/后文中）
                    figure_number = ""
                    # 匹配 "见图2.5"、"图2.5"、"见图 2.5" 等
                    fig_match = re.search(r'[见如]?图\s*(\d+\.?\d*)', doc_text)
                    if fig_match:
                        figure_number = fig_match.group(1)

                    # 如果 doc 中没有，尝试从 section 中提取
                    section = meta.get('section') or meta.get('section_path', '')
                    if not figure_number and section:
                        fig_match = re.search(r'[见如]?图\s*(\d+\.?\d*)', section)
                        if fig_match:
                            figure_number = fig_match.group(1)

                    # 传入图片元数据，增强 VLM 描述
                    image_metadata = {
                        'section': section,
                        'page': meta.get('page'),
                        'caption': meta.get('caption', ''),
                        'source': meta.get('source', ''),
                        'figure_number': figure_number,  # 添加提取的图号
                        'doc_text': doc_text  # 添加完整文档文本
                    }
                    vlm_desc = await lazy_vlm_description(
                        meta.get('id', ''),
                        image_path,
                        kb_name,
                        metadata=image_metadata
                    )
                    ctx['doc'] = vlm_desc
                    ctx['vlm_enhanced'] = True
                except Exception as e:
                    logger.warning(f"VLM 懒加载失败: {e}")

        # 表格切片：同时处理摘要和关联图片的 VLM 描述
        elif chunk_type == 'table':
            doc_text = ctx.get('doc', '')

            # 1. 懒加载表格摘要（高分切片）
            if not meta.get('has_summary'):
                score = meta.get('score', 0)
                if score > 0.7:  # 只对高相关表格生成摘要
                    try:
                        summary = await lazy_table_summary(
                            meta.get('id', ''),
                            doc_text,
                            kb_name
                        )
                        # 摘要作为补充信息
                        ctx['summary'] = summary
                        ctx['llm_enhanced'] = True
                    except Exception as e:
                        logger.warning(f"表格摘要懒加载失败: {e}")

            # 2. 表格有关联图片时，懒加载 VLM 描述
            if image_path and not meta.get('has_vlm_desc'):
                try:
                    import re

                    # 提取表号（如 "表2.2"、"见表2.1"）
                    table_number = ""
                    # 匹配 "表2.2"、"见表2.2"、"见表 2.2" 等
                    table_match = re.search(r'[见如]?表\s*(\d+\.?\d*)', doc_text)
                    if table_match:
                        table_number = table_match.group(1)

                    # 如果 doc 中没有，尝试从 section 中提取
                    section = meta.get('section') or meta.get('section_path', '')
                    if not table_number and section:
                        table_match = re.search(r'[见如]?表\s*(\d+\.?\d*)', section)
                        if table_match:
                            table_number = table_match.group(1)

                    # 构建表格图片元数据
                    table_image_metadata = {
                        'section': section,
                        'page': meta.get('page'),
                        'caption': meta.get('caption', ''),
                        'source': meta.get('source', ''),
                        'table_number': table_number,  # 表号
                        'figure_number': table_number,  # 兼容字段
                        'doc_text': doc_text,
                        'is_table': True  # 标记为表格图片
                    }
                    vlm_desc = await lazy_vlm_description(
                        meta.get('id', ''),
                        image_path,
                        kb_name,
                        metadata=table_image_metadata
                    )
                    # 表格图片描述作为补充信息
                    ctx['image_description'] = vlm_desc
                    ctx['vlm_enhanced'] = True
                except Exception as e:
                    logger.warning(f"表格图片 VLM 懒加载失败: {e}")
