# -*- coding: utf-8 -*-
"""
OpenDataLoader PDF 解析模块

使用 opendataloader-pdf 库替代 pdfplumber，提供更高质量的 PDF 解析：
- 保留文档语义结构（标题层级）
- 高精度表格提取
- 支持 bounding box 坐标溯源
"""

import os
import json
import re
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

import opendataloader_pdf


@dataclass
class ChunkMetadata:
    """分块元数据"""
    title: str                    # 章节标题
    content: str                  # 章节内容
    level: int                    # 标题级别 (1-6)
    page_start: int = 1           # 起始页码
    page_end: int = 1             # 结束页码
    section_path: str = ""        # 完整章节路径 (如 "第一章 > 1.1 背景")
    bbox: Optional[List[float]] = None  # 边界框坐标 [x0, y0, x1, y1]
    source_file: str = ""         # 源文件名
    chunk_type: str = "section"   # 类型: section, table, image
    table_data: Optional[str] = None  # 表格原始数据（如果是表格）
    images: Optional[List[Dict]] = None  # 关联的图片信息（新增）


def parse_pdf_with_odl(
    pdf_path: str,
    output_dir: Optional[str] = None,
    use_struct_tree: bool = True,
    use_hybrid: bool = False,
    hybrid_url: Optional[str] = None,
    extract_images: bool = True,
    images_output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 OpenDataLoader PDF 解析文档

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录，默认使用临时目录
        use_struct_tree: 是否使用 PDF 结构树（Tagged PDF）
        use_hybrid: 是否使用混合模式（需要后端服务）
        hybrid_url: 混合模式服务器地址
        extract_images: 是否提取图片
        images_output_dir: 图片输出目录

    Returns:
        {
            "markdown": "转换后的 Markdown 内容",
            "json_data": {...},  # JSON 结构化数据
            "chunks": [ChunkMetadata, ...],  # 智能分块结果
            "tables": ["表格1", ...],  # 提取的表格列表
            "images": [ImageInfo, ...],  # 提取的图片列表
            "metadata": {...}  # 文档元数据
        }
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    # 创建临时输出目录
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="odl_pdf_")
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # 构建转换参数
    convert_kwargs = {
        "input_path": str(pdf_path),
        "output_dir": str(output_dir),
        "format": ["markdown", "json"],
        "use_struct_tree": use_struct_tree,
        "reading_order": "xycut",  # 使用 XY-Cut++ 算法
        "table_method": "cluster",  # 更好的表格检测
    }

    # 混合模式配置
    if use_hybrid:
        convert_kwargs["hybrid"] = "docling-fast"
        convert_kwargs["hybrid_fallback"] = True  # 启用 Java 回退，避免页面丢失
        if hybrid_url:
            convert_kwargs["hybrid_url"] = hybrid_url

    try:
        # 执行转换
        opendataloader_pdf.convert(**convert_kwargs)

        # 读取输出文件
        base_name = pdf_path.stem
        markdown_path = Path(output_dir) / f"{base_name}.md"
        json_path = Path(output_dir) / f"{base_name}.json"

        markdown_content = ""
        json_data = {}

        if markdown_path.exists():
            with open(markdown_path, "r", encoding="utf-8") as f:
                markdown_content = f.read()

        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

        # 提取表格
        tables = extract_tables_from_json(json_data)

        # 智能分块
        chunks = smart_chunk_by_section(
            markdown_content,
            json_data,
            source_file=pdf_path.name
        )

        # 提取图片
        images = []
        if extract_images:
            from parsers.image_extractor import extract_images_from_pdf, get_images_base_path

            img_output = images_output_dir or get_images_base_path()
            try:
                images = extract_images_from_pdf(str(pdf_path), img_output)

                # 为分块关联图片信息
                if images:
                    from parsers.image_extractor import enrich_chunks_with_images
                    chunks = enrich_chunks_with_images(chunks, images, pdf_path.name)

            except Exception as e:
                print(f"[警告] 图片提取失败: {e}")

        return {
            "markdown": markdown_content,
            "json_data": json_data,
            "chunks": chunks,
            "tables": tables,
            "images": images,
            "metadata": {
                "source_file": pdf_path.name,
                "output_dir": str(output_dir),
                "use_struct_tree": use_struct_tree,
                "use_hybrid": use_hybrid,
                "image_count": len(images)
            }
        }

    except Exception as e:
        raise RuntimeError(f"PDF 解析失败: {e}") from e


def smart_chunk_by_section(
    markdown_content: str,
    json_data: Optional[Dict] = None,
    source_file: str = ""
) -> List[ChunkMetadata]:
    """
    按章节标题智能分块，保留语义完整性

    分块规则：
    1. 一级标题（#）单独成块，作为章节索引
    2. 二级标题（##）及内容作为基本分块单元
    3. 三级以下标题内容合并到上级标题
    4. 表格、代码块强制保留完整性
    5. 空内容标题合并到下一个有内容的块

    Args:
        markdown_content: Markdown 格式内容
        json_data: JSON 结构化数据（用于提取坐标等元信息）
        source_file: 源文件名

    Returns:
        分块列表
    """
    if not markdown_content.strip():
        return []

    chunks = []
    lines = markdown_content.split('\n')

    current_chunk = None
    section_stack = []  # 用于追踪章节层级路径
    in_code_block = False
    in_table = False
    table_buffer = []

    for i, line in enumerate(lines):
        # 检测代码块
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            if current_chunk:
                current_chunk.content += line + '\n'
            continue

        # 检测表格
        if '|' in line and not in_code_block:
            if not in_table:
                in_table = True
                table_buffer = []
            table_buffer.append(line)
            continue
        elif in_table and not line.strip().startswith('|'):
            # 表格结束
            in_table = False
            if current_chunk:
                current_chunk.content += '\n'.join(table_buffer) + '\n'
            table_buffer = []

        # 跳过代码块内的内容（已添加）
        if in_code_block:
            if current_chunk:
                current_chunk.content += line + '\n'
            continue

        # 处理标题
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            # 保存当前块
            if current_chunk and current_chunk.content.strip():
                current_chunk.page_end = estimate_page_from_position(
                    i, len(lines), json_data
                )
                chunks.append(current_chunk)

            # 更新章节路径
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, title))

            # 创建新块
            current_chunk = ChunkMetadata(
                title=title,
                content="",
                level=level,
                page_start=estimate_page_from_position(i, len(lines), json_data),
                section_path=" > ".join([s[1] for s in section_stack]),
                source_file=source_file,
                chunk_type="section"
            )
        else:
            # 普通内容
            if current_chunk:
                current_chunk.content += line + '\n'
            elif line.strip():
                # 没有标题的内容，创建默认块
                current_chunk = ChunkMetadata(
                    title="文档开头",
                    content=line + '\n',
                    level=0,
                    page_start=1,
                    section_path="文档开头",
                    source_file=source_file,
                    chunk_type="section"
                )

    # 处理最后的表格缓冲
    if in_table and table_buffer:
        if current_chunk:
            current_chunk.content += '\n'.join(table_buffer) + '\n'

    # 保存最后一个块
    if current_chunk and current_chunk.content.strip():
        current_chunk.page_end = estimate_page_from_position(
            len(lines), len(lines), json_data
        )
        chunks.append(current_chunk)

    # 后处理：合并小片段
    chunks = merge_small_chunks(chunks)

    # 从 JSON 数据提取坐标信息
    if json_data:
        chunks = enrich_chunks_with_bbox(chunks, json_data)

    return chunks


def merge_small_chunks(
    chunks: List[ChunkMetadata],
    min_content_length: int = 100
) -> List[ChunkMetadata]:
    """
    合并内容过小的分块

    Args:
        chunks: 原始分块列表
        min_content_length: 最小内容长度阈值

    Returns:
        合并后的分块列表
    """
    if not chunks:
        return chunks

    merged = []
    i = 0

    while i < len(chunks):
        current = chunks[i]

        # 如果当前块内容太少且不是顶级标题，尝试合并到下一个块
        while (i + 1 < len(chunks) and
               len(current.content.strip()) < min_content_length and
               current.level > 1):
            next_chunk = chunks[i + 1]
            # 合并内容
            current.content += f"\n\n## {next_chunk.title}\n\n{next_chunk.content}"
            current.page_end = next_chunk.page_end
            i += 1

        merged.append(current)
        i += 1

    return merged


def estimate_page_from_position(
    line_index: int,
    total_lines: int,
    json_data: Optional[Dict]
) -> int:
    """
    根据行位置估算页码

    Args:
        line_index: 当前行索引
        total_lines: 总行数
        json_data: JSON 数据（可能包含页码信息）

    Returns:
        估算的页码
    """
    # 尝试从 JSON 数据获取精确页码
    if json_data and "pages" in json_data:
        # 简化处理：基于行数比例估算
        # 实际应用中可以从 JSON 中提取每个元素的页码
        pass

    # 默认基于行数比例估算
    if total_lines == 0:
        return 1

    # 假设每页约 40-50 行
    estimated_page = max(1, (line_index // 45) + 1)
    return estimated_page


def extract_tables_from_json(json_data: Dict) -> List[str]:
    """
    从 JSON 数据中提取表格

    Args:
        json_data: OpenDataLoader 输出的 JSON 数据

    Returns:
        表格内容列表（Markdown 格式）
    """
    tables = []

    if not json_data:
        return tables

    # 遍历 JSON 结构查找表格
    def find_tables_recursive(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "table":
                # 提取表格内容
                table_md = obj.get("markdown", "")
                if table_md:
                    tables.append(table_md)
            for value in obj.values():
                find_tables_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                find_tables_recursive(item)

    find_tables_recursive(json_data)
    return tables


def enrich_chunks_with_bbox(
    chunks: List[ChunkMetadata],
    json_data: Dict
) -> List[ChunkMetadata]:
    """
    从 JSON 数据中提取边界框坐标信息

    Args:
        chunks: 分块列表
        json_data: JSON 数据

    Returns:
        添加了坐标信息的分块列表
    """
    if not json_data:
        return chunks

    # 构建标题到坐标的映射
    title_to_bbox = {}

    def find_bboxes_recursive(obj, current_page=1):
        if isinstance(obj, dict):
            bbox = obj.get("bbox")
            text = obj.get("text", "")
            if bbox and text:
                # 提取标题文本
                title_match = re.match(r'^(#{1,6})\s+(.+)$', text)
                if title_match:
                    title = title_match.group(2).strip()
                    title_to_bbox[title] = {
                        "bbox": bbox,
                        "page": obj.get("page", current_page)
                    }
            for value in obj.values():
                find_bboxes_recursive(value, current_page)
        elif isinstance(obj, list):
            for item in obj:
                find_bboxes_recursive(item, current_page)

    find_bboxes_recursive(json_data)

    # 为每个块添加坐标信息
    for chunk in chunks:
        if chunk.title in title_to_bbox:
            info = title_to_bbox[chunk.title]
            chunk.bbox = info["bbox"]
            chunk.page_start = info.get("page", chunk.page_start)

    return chunks


def get_chapter_content_for_exam(
    chunks: List[ChunkMetadata],
    keywords: List[str],
    max_chunks: int = 5,
    min_content_length: int = 200
) -> List[Dict[str, Any]]:
    """
    为出题功能获取相关章节内容

    Args:
        chunks: 分块列表
        keywords: 关键词列表
        max_chunks: 最大返回块数
        min_content_length: 最小内容长度

    Returns:
        [
            {
                "title": "章节标题",
                "content": "完整内容",
                "section_path": "章节路径",
                "page_range": "1-2",
                "source_file": "文件名"
            }
        ]
    """
    import jieba

    # 关键词分词
    keyword_tokens = set()
    for kw in keywords:
        keyword_tokens.update(jieba.cut(kw))

    # 计算每个块的相关性分数
    scored_chunks = []
    for chunk in chunks:
        if len(chunk.content.strip()) < min_content_length:
            continue

        # 分词
        chunk_tokens = set(jieba.cut(chunk.content + chunk.title))

        # 计算交集
        common_tokens = keyword_tokens & chunk_tokens
        score = len(common_tokens)

        if score > 0:
            scored_chunks.append((score, chunk))

    # 按分数排序，取前 N 个
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    top_chunks = scored_chunks[:max_chunks]

    # 格式化输出
    result = []
    for score, chunk in top_chunks:
        result.append({
            "title": chunk.title,
            "content": chunk.content.strip(),
            "section_path": chunk.section_path,
            "page_range": f"{chunk.page_start}-{chunk.page_end}",
            "source_file": chunk.source_file,
            "relevance_score": score
        })

    return result


# 便捷函数：处理单个 PDF 并返回分块结果
def process_pdf_for_rag(
    pdf_path: str,
    output_dir: Optional[str] = None
) -> Tuple[List[str], List[Dict]]:
    """
    处理 PDF 并返回适合 RAG 系统的格式

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录

    Returns:
        (documents, metadatas) - 文档列表和元数据列表
    """
    result = parse_pdf_with_odl(pdf_path, output_dir)

    documents = []
    metadatas = []

    for chunk in result["chunks"]:
        documents.append(chunk.content)
        metadatas.append(asdict(chunk))

    return documents, metadatas


if __name__ == "__main__":
    # 测试代码
    import sys

    # Windows 控制台编码修复
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("用法: python pdf_parser_odl.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    print(f"正在解析: {pdf_path}")
    result = parse_pdf_with_odl(pdf_path)

    print(f"\n解析完成:")
    print(f"- Markdown 长度: {len(result['markdown'])} 字符")
    print(f"- 分块数量: {len(result['chunks'])}")
    print(f"- 表格数量: {len(result['tables'])}")

    print("\n分块预览:")
    for i, chunk in enumerate(result['chunks'][:5]):
        print(f"\n--- 块 {i+1}: {chunk.title} (级别 {chunk.level}) ---")
        print(f"路径: {chunk.section_path}")
        print(f"页码: {chunk.page_start}-{chunk.page_end}")
        print(f"内容长度: {len(chunk.content)} 字符")
        content = chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
        # 安全打印，替换无法编码的字符
        safe_content = content.encode('utf-8', errors='replace').decode('utf-8')
        print(safe_content)
