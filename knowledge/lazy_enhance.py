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


async def lazy_vlm_description(chunk_id: str, image_path: str, kb_name: str) -> str:
    """
    懒加载 VLM 描述

    触发条件：图片切片被检索命中

    Args:
        chunk_id: 切片 ID
        image_path: 图片路径（相对路径或绝对路径）
        kb_name: 知识库名称

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

    # 2. 调用 VLM
    logger.info(f"VLM 懒加载: {image_path}")
    kb_manager = get_kb_manager()
    description = kb_manager._generate_image_description(full_image_path)

    # 3. 写入缓存
    VLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(description, encoding='utf-8')

    # 4. 更新向量库（可选：后台更新）
    try:
        collection = kb_manager.get_collection(kb_name)
        result = collection.get(ids=[chunk_id], include=['metadatas'])
        if result['metadatas']:
            collection.update(
                ids=[chunk_id],
                metadatas=[{
                    **result['metadatas'][0],
                    'has_vlm_desc': True,
                    'vlm_desc': description
                }]
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

        # 图片切片：懒加载 VLM 描述
        if chunk_type in ('image', 'chart') and not meta.get('has_vlm_desc'):
            image_path = meta.get('image_path', '')
            if image_path:
                try:
                    vlm_desc = await lazy_vlm_description(
                        meta.get('id', ''),
                        image_path,
                        kb_name
                    )
                    ctx['doc'] = vlm_desc
                    ctx['vlm_enhanced'] = True
                except Exception as e:
                    logger.warning(f"VLM 懒加载失败: {e}")

        # 表格切片：懒加载 LLM 摘要（可选，仅高分切片）
        elif chunk_type == 'table' and not meta.get('has_summary'):
            score = meta.get('score', 0)
            if score > 0.7:  # 只对高相关表格生成摘要
                try:
                    table_md = ctx.get('doc', '')
                    summary = await lazy_table_summary(
                        meta.get('id', ''),
                        table_md,
                        kb_name
                    )
                    # 摘要作为补充信息
                    ctx['summary'] = summary
                    ctx['llm_enhanced'] = True
                except Exception as e:
                    logger.warning(f"表格摘要懒加载失败: {e}")
