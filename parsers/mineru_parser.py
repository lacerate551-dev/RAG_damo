# -*- coding: utf-8 -*-
"""
MinerU 统一文档解析模块 (v3.0+)

使用 MinerU v3.0+ 进行高质量多格式文档解析：
- PDF: 表格识别率 95%+，支持 109 种语言 OCR
- DOCX: 原生 Word 解析，速度提升数十倍，无幻觉
- XLSX: Excel 表格解析
- PPTX: PowerPoint 幻灯片解析
- 图片: 直接 OCR 识别

统一输出格式：
- 保留标题层级（text_level）
- 输出 Markdown + JSON 双格式
- 表格输出 HTML 格式

依赖：
    pip install "mineru[all]"
    mineru-models-download -s huggingface -m all
"""

import os
import json
import tempfile
import shutil
import subprocess
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse
import re
import logging

logger = logging.getLogger(__name__)

# 支持的文件格式
SUPPORTED_FORMATS = {
    '.pdf': 'PDF 文档',
    '.docx': 'Word 文档',
    '.xlsx': 'Excel 表格',
    '.pptx': 'PowerPoint 幻灯片',
    '.png': 'PNG 图片',
    '.jpg': 'JPEG 图片',
    '.jpeg': 'JPEG 图片',
    '.bmp': 'BMP 图片',
    '.tiff': 'TIFF 图片',
}


def normalize_image_path(path: str) -> str:
    """
    规范化图片路径，处理各种边界情况

    Args:
        path: 原始图片路径（可能包含 query 参数、相对路径等）

    Returns:
        规范化后的文件名
    """
    # 去掉 query 参数
    path = urlparse(path).path
    # 只保留文件名
    return os.path.basename(path)


def extract_images_from_markdown(content: str) -> List[Dict]:
    """
    从 Markdown/HTML 中提取图片引用

    Args:
        content: Markdown 或 HTML 内容

    Returns:
        [{"id": "abc.jpg", "order": 1}, ...]
    """
    seen = {}  # 用于去重保序
    order = 0

    # 匹配 Markdown 格式: ![alt](path)
    md_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    for match in re.finditer(md_pattern, content):
        img_path = match.group(2)
        img_id = normalize_image_path(img_path)
        if img_id and img_id not in seen:
            order += 1
            seen[img_id] = {"id": img_id, "order": order}

    # 匹配 HTML 格式: <img src="path"/>
    html_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    for match in re.finditer(html_pattern, content):
        img_path = match.group(1)
        img_id = normalize_image_path(img_path)
        if img_id and img_id not in seen:
            order += 1
            seen[img_id] = {"id": img_id, "order": order}

    return list(seen.values())


@dataclass
class MinerUChunk:
    """MinerU 解析结果分块"""
    content: str                      # 文本内容
    chunk_type: str                   # 类型: text, table, image, equation
    page_start: int = 1               # 起始页码
    page_end: int = 1                 # 结束页码
    text_level: int = 0               # 标题级别 (0=body, 1=h1, 2=h2...)
    title: str = ""                   # 标题文本
    section_path: str = ""            # 章节路径
    bbox: Optional[List[float]] = None  # 边界框 [x0, y0, x1, y1]
    source_file: str = ""             # 源文件名
    table_html: Optional[str] = None  # 表格 HTML（如果是表格）
    image_path: Optional[str] = None  # 图片路径（独立图片）
    images: Optional[List[Dict]] = None  # 关联图片列表: [{"id": "abc.jpg", "order": 1}]
    # 图片上下文（用于语义检索）
    context_before: str = ""          # 图片前的文本上下文
    context_after: str = ""           # 图片后的文本上下文


def parse_with_mineru(
    file_path: str,
    output_dir: Optional[str] = None,
    lang: str = "ch",
    enable_table: bool = True,
    enable_formula: bool = True,
    backend: str = "pipeline",
    start_page: int = 0,
    end_page: int = 99999
) -> Dict[str, Any]:
    """
    使用 MinerU 解析文档（支持 PDF、DOCX、XLSX、PPTX、图片）

    Args:
        file_path: 文档文件路径
        output_dir: 输出目录，默认使用临时目录
        lang: 语言代码 (ch, en, etc.)
        enable_table: 启用表格识别
        enable_formula: 启用公式识别
        backend: 解析后端
            - "pipeline": 通用模式（推荐）
            - "vlm-auto-engine": 高精度模式
            - "hybrid-auto-engine": 新一代高精度方案
        start_page: 起始页码（0-indexed，仅 PDF 有效）
        end_page: 结束页码（仅 PDF 有效）

    Returns:
        {
            'markdown': str,           # Markdown 内容
            'chunks': List[MinerUChunk],  # 结构化分块
            'tables': List[str],       # 表格列表
            'images': List[str],       # 图片列表
            'content_list': List[Dict] # 原始 content_list
        }
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 检查文件格式
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError(
            f"不支持的文件格式: {suffix}。"
            f"支持格式: {', '.join(SUPPORTED_FORMATS.keys())}"
        )

    logger.info(f"使用 MinerU 解析 {SUPPORTED_FORMATS.get(suffix, '文档')}: {file_path.name}")

    # 创建输出目录
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="mineru_")
        cleanup_output = True
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cleanup_output = False

    # 构建 mineru 命令
    # 使用虚拟环境中的 mineru
    import sys
    venv_dir = Path(sys.executable).parent
    mineru_exe = venv_dir / "mineru.exe"
    if not mineru_exe.exists():
        mineru_exe = venv_dir / "mineru"
    if not mineru_exe.exists():
        mineru_exe = "mineru"  # 回退到系统 PATH

    cmd = [
        str(mineru_exe),
        "-p", str(file_path),
        "-o", str(output_dir),
        "-m", "auto",
        "-b", backend,
        "-l", lang,
        "-s", str(start_page),
        "-e", str(end_page) if end_page < 99999 else str(99999),
        "-f", str(enable_formula).lower(),
        "-t", str(enable_table).lower()
    ]

    try:
        # 执行 MinerU 命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            # 使用系统默认编码，避免 UTF-8 解码错误
            encoding=None,
            errors='replace',
            timeout=600  # 10分钟超时
        )

        if result.returncode != 0:
            # 安全解码 stderr
            if result.stderr:
                stderr_output = result.stderr.decode('utf-8', errors='replace') if isinstance(result.stderr, bytes) else str(result.stderr)
            else:
                stderr_output = ""
            logger.error(f"MinerU 解析失败: {stderr_output}")
            raise RuntimeError(f"MinerU 解析失败: {stderr_output}")

        # 解析输出结果
        return _parse_mineru_output(file_path, output_dir)

    except subprocess.TimeoutExpired:
        raise RuntimeError("MinerU 解析超时")
    except FileNotFoundError:
        raise RuntimeError(
            "MinerU 未安装或不在 PATH 中，请运行: pip install \"mineru[all]\""
        )
    except Exception as e:
        logger.error(f"MinerU 解析失败: {e}")
        raise
    finally:
        # 清理临时目录
        if cleanup_output and os.path.exists(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)


def _detect_heading_level(text: str) -> int:
    """
    启发式标题识别

    用于 MinerU 解析 DOCX 等 Office 格式时不提供 text_level 的情况。

    Args:
        text: 文本内容

    Returns:
        标题级别 (0=正文, 1=h1, 2=h2, 3=h3)
    """
    import re

    text = text.strip()

    # 空文本
    if not text:
        return 0

    # 中文章节标题模式
    # 第一章、第二章、... -> h1
    if re.match(r'^第[一二三四五六七八九十百千万]+[章节篇部]', text):
        return 1

    # 第一条、第二条、... -> h2 (条文编号)
    if re.match(r'^第[一二三四五六七八九十百千万]+[条款]', text):
        return 2

    # 数字章节: 1. 2. 3. 或 1、2、3、
    # 一级标题: 1. 2. 3. (单数字)
    if re.match(r'^\d+[\.、\s]', text):
        # 短文本可能是标题
        if len(text) < 50:
            return 1

    # 二级标题: 1.1 1.2 2.1 等
    if re.match(r'^\d+\.\d+[\.、\s]', text):
        if len(text) < 80:
            return 2

    # 三级标题: 1.1.1 1.1.2 等
    if re.match(r'^\d+\.\d+\.\d+[\.、\s]', text):
        if len(text) < 100:
            return 3

    # 英文章节标题
    # Chapter 1, Section 2, etc.
    if re.match(r'^(Chapter|Section|Part|Chapter\s+\d+|Section\s+\d+)', text, re.IGNORECASE):
        return 1

    # 短文本 + 加粗标记 (**xxx**) 可能是标题
    if re.match(r'^\*\*.+\*\*$', text) and len(text) < 50:
        return 2

    # 非常短的文本 (< 20 字符) 可能是标题
    # 但需要排除常见的非标题短文本
    if len(text) < 20 and not re.match(r'^[\d\s\.,;:!?，。；：！？、]+$', text):
        # 排除纯数字、纯标点
        if re.search(r'[\u4e00-\u9fff]', text):  # 包含中文
            return 2

    return 0


def _parse_mineru_output(file_path: Path, output_dir) -> Dict[str, Any]:
    """
    解析 MinerU 输出结果

    Args:
        file_path: 源文件路径
        output_dir: 输出目录

    Returns:
        解析结果字典
    """
    chunks = []
    tables = []
    images = []
    section_stack = []  # 追踪章节层级
    markdown_parts = []

    # 确保 output_dir 是 Path 对象
    output_dir = Path(output_dir)

    # 查找输出文件
    # 不同格式的输出目录不同：
    # - PDF: output/文件名/auto/
    # - DOCX/XLSX/PPTX: output/文件名/office/
    doc_name = file_path.stem
    auto_dir = output_dir / doc_name / "auto"
    office_dir = output_dir / doc_name / "office"

    # 选择正确的输出目录
    if auto_dir.exists():
        output_subdir = auto_dir
    elif office_dir.exists():
        output_subdir = office_dir
    else:
        raise RuntimeError(f"MinerU 输出目录不存在: {auto_dir} 或 {office_dir}")

    # 读取 content_list.json
    content_list_path = output_subdir / f"{doc_name}_content_list.json"
    if not content_list_path.exists():
        content_list_path = output_subdir / f"{doc_name}_content_list_v2.json"

    content_list = []
    if content_list_path.exists():
        with open(content_list_path, 'r', encoding='utf-8') as f:
            content_list = json.load(f)

    # 读取 Markdown
    md_path = output_subdir / f"{doc_name}.md"
    markdown_content = ""
    if md_path.exists():
        with open(md_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()

    # 第一遍扫描：收集所有文本内容（用于构建图片上下文）
    text_items = []  # [(index, text, page_idx), ...]
    for idx, item in enumerate(content_list):
        if item.get("type") == "text":
            text = item.get("text", "").strip()
            if text:
                text_items.append((idx, text, item.get("page_idx", 0)))

    def get_context_for_image(image_idx: int, page_idx: int, window: int = 3) -> tuple:
        """获取图片前后的文本上下文"""
        context_before = []
        context_after = []

        # 查找图片前后的文本项
        for item_idx, text, item_page in text_items:
            if item_idx < image_idx and item_page >= page_idx - 1:
                # 图片之前的文本（同页或上一页）
                context_before.append(text)
            elif item_idx > image_idx and item_page <= page_idx + 1:
                # 图片之后的文本（同页或下一页）
                context_after.append(text)

        # 只保留最近的 window 条
        context_before = context_before[-window:] if context_before else []
        context_after = context_after[:window] if context_after else []

        return " ".join(context_before), " ".join(context_after)

    # 解析 content_list
    for idx, item in enumerate(content_list):
        item_type = item.get("type", "text")
        page_idx = item.get("page_idx", 0)
        bbox = item.get("bbox", [])
        text_level = item.get("text_level", 0)

        if item_type == "text":
            text = item.get("text", "")

            # 启发式标题识别（当 text_level 为 0 时）
            if text_level == 0:
                text_level = _detect_heading_level(text)

            # 处理标题
            title = ""
            if text_level > 0:
                title = text.strip()
                # 更新章节栈
                while section_stack and section_stack[-1][0] >= text_level:
                    section_stack.pop()
                section_stack.append((text_level, title))

            # 构建章节路径
            section_path = " > ".join([s[1] for s in section_stack])

            # 构建 Markdown
            if text_level > 0:
                md_line = f"{'#' * text_level} {text}"
            else:
                md_line = text
            markdown_parts.append(md_line)

            chunk = MinerUChunk(
                content=text,
                chunk_type="heading" if text_level > 0 else "text",
                page_start=page_idx + 1,
                page_end=page_idx + 1,
                text_level=text_level,
                title=title,
                section_path=section_path,
                bbox=bbox,
                source_file=file_path.name
            )
            chunks.append(chunk)

        elif item_type == "table":
            table_body = item.get("table_body", "")
            table_caption = item.get("table_caption", "")
            # 表格也可能有图片形式（img_path）
            img_path = item.get("img_path", "")

            section_path = " > ".join([s[1] for s in section_stack])

            markdown_parts.append(f"\n| 表格 |")
            if table_body:
                md_table = html_table_to_markdown(table_body)
                markdown_parts.append(md_table)
            else:
                md_table = ""

            # 提取表格中的嵌入图片
            table_images = extract_images_from_markdown(md_table) if md_table else []

            chunk = MinerUChunk(
                content=table_caption or "表格",
                chunk_type="table",
                page_start=page_idx + 1,
                page_end=page_idx + 1,
                title=table_caption or "表格",
                section_path=section_path,
                bbox=bbox,
                source_file=file_path.name,
                table_html=table_body,
                image_path=img_path,  # 表格的独立图片形式
                images=table_images if table_images else None  # 嵌入图片列表
            )
            chunks.append(chunk)
            if table_body:
                tables.append(table_body)
            # 表格图片也加入 images 列表
            if img_path:
                images.append(img_path)

        elif item_type in ("image", "chart"):
            # 处理图片和图表类型（MinerU 将图表识别为 chart 类型）
            img_path = item.get("img_path", "")
            caption = item.get("caption", "")

            section_path = " > ".join([s[1] for s in section_stack])

            markdown_parts.append(f"\n![{caption}]({img_path})")

            # 图表类型标记为 chart，便于后续区分处理
            chunk_type = "chart" if item_type == "chart" else "image"

            # 获取图片上下文
            context_before, context_after = get_context_for_image(idx, page_idx)

            chunk = MinerUChunk(
                content=caption or ("图表" if item_type == "chart" else "图片"),
                chunk_type=chunk_type,
                page_start=page_idx + 1,
                page_end=page_idx + 1,
                title=caption or ("图表" if item_type == "chart" else "图片"),
                section_path=section_path,
                bbox=bbox,
                source_file=file_path.name,
                image_path=img_path,
                context_before=context_before,
                context_after=context_after
            )
            chunks.append(chunk)
            if img_path:
                images.append(img_path)

    # 如果没有从 content_list 解析到内容，使用 Markdown
    if not chunks and markdown_content:
        markdown_parts = [markdown_content]

    # 后处理：过滤空切片 → 合并碎片 → 拆分超长
    # 使用配置中的切片约束
    try:
        from config import MIN_CHUNK_SIZE, MAX_CHUNK_SIZE
        min_merge = MIN_CHUNK_SIZE // 2  # 合并阈值为最小切片的一半
        max_size = MAX_CHUNK_SIZE
    except ImportError:
        min_merge = 100
        max_size = 1200

    chunks = _post_process_chunks(chunks, min_merge_size=min_merge, max_chunk_size=max_size)

    return {
        'markdown': "\n".join(markdown_parts),
        'chunks': chunks,
        'tables': tables,
        'images': images,
        'content_list': content_list
    }


def _post_process_chunks(
    chunks: List[MinerUChunk],
    min_merge_size: int = 100,
    max_merged_size: int = 800,
    max_chunk_size: int = 1000
) -> List[MinerUChunk]:
    """
    后处理：过滤空切片 → 合并碎片 → 拆分超长

    解决三个问题：
    1. 空切片（0 字符）入库
    2. 标题/短文本独立成片导致碎片化
    3. 超长切片超过 Embedding 模型的 token 限制

    策略：
    - 标题 chunk 与下方第一个正文 chunk 合并
    - 连续短文本 chunk（< min_merge_size）合并
    - 合并后超过 max_merged_size 则停止合并
    - 表格、图片 chunk 保持独立不参与合并
    - 最终检查：超过 max_chunk_size 的 chunk 使用 split_text_with_limit 拆分

    Args:
        chunks: 原始 chunk 列表
        min_merge_size: 短于此长度的 chunk 触发合并
        max_merged_size: 合并后的最大字符数
        max_chunk_size: 单个 chunk 的硬性上限

    Returns:
        处理后的 chunk 列表
    """
    if not chunks:
        return []

    # Phase 1: 过滤空切片（统一处理 list/string 类型）
    filtered = []
    for c in chunks:
        if not c.content:
            continue
        # 统一转字符串
        if isinstance(c.content, list):
            c.content = '\n'.join(str(item) for item in c.content)
        if c.content.strip():
            filtered.append(c)
    chunks = filtered

    if not chunks:
        return []

    # Phase 2: 合并碎片
    merged = []
    buffer = None  # 当前合并缓冲

    for chunk in chunks:
        # 表格、图片和图表不参与合并，直接输出
        if chunk.chunk_type in ('table', 'image', 'chart', 'equation'):
            if buffer:
                merged.append(buffer)
                buffer = None
            merged.append(chunk)
            continue

        # 标题 chunk（text_level > 0），开始新的合并组
        if chunk.text_level > 0:
            if buffer:
                merged.append(buffer)
            # 标题作为新缓冲的起点
            buffer = MinerUChunk(
                content=chunk.content,
                chunk_type='text',
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text_level=chunk.text_level,
                title=chunk.title,
                section_path=chunk.section_path,
                bbox=chunk.bbox,
                source_file=chunk.source_file,
            )
            continue

        # 正文 chunk
        content_len = len(chunk.content.strip())

        if buffer is None:
            # 没有缓冲，开始新缓冲
            if content_len < min_merge_size:
                buffer = MinerUChunk(
                    content=chunk.content,
                    chunk_type='text',
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    text_level=chunk.text_level,
                    title=chunk.title,
                    section_path=chunk.section_path,
                    bbox=chunk.bbox,
                    source_file=chunk.source_file,
                )
            else:
                # 足够长，直接输出
                merged.append(chunk)
        else:
            # 有缓冲，尝试合并
            combined_len = len(buffer.content) + 1 + content_len
            if combined_len <= max_merged_size:
                # 合并
                buffer.content = buffer.content.rstrip() + '\n' + chunk.content
                buffer.page_end = chunk.page_end
            else:
                # 超过上限，输出缓冲，当前 chunk 开始新缓冲或直接输出
                merged.append(buffer)
                if content_len < min_merge_size:
                    buffer = MinerUChunk(
                        content=chunk.content,
                        chunk_type='text',
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        text_level=chunk.text_level,
                        title=chunk.title,
                        section_path=chunk.section_path,
                        bbox=chunk.bbox,
                        source_file=chunk.source_file,
                    )
                else:
                    buffer = None
                    merged.append(chunk)

    # 刷新最后的缓冲
    if buffer:
        merged.append(buffer)

    # Phase 3: 拆分超长切片
    result = []
    for chunk in merged:
        if chunk.chunk_type in ('table', 'image', 'chart', 'equation'):
            result.append(chunk)
            continue

        if len(chunk.content) > max_chunk_size:
            # 使用已有的 split_text_with_limit 函数拆分
            try:
                from core.chunker import split_text_with_limit
                sub_texts = split_text_with_limit(
                    chunk.content,
                    chunk_size=max_chunk_size,
                    overlap=50,
                    max_length=max_chunk_size
                )
                for i, sub_text in enumerate(sub_texts):
                    sub_chunk = MinerUChunk(
                        content=sub_text,
                        chunk_type=chunk.chunk_type,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        text_level=chunk.text_level if i == 0 else 0,
                        title=chunk.title if i == 0 else '',
                        section_path=chunk.section_path,
                        bbox=chunk.bbox,
                        source_file=chunk.source_file,
                    )
                    result.append(sub_chunk)
            except ImportError:
                logger.warning("split_text_with_limit 不可用，保留原始超长切片")
                result.append(chunk)
        else:
            result.append(chunk)

    logger.info(
        f"切片后处理: {len(chunks)} → {len(result)} "
        f"(过滤空切片+合并碎片+拆分超长)"
    )
    return result


def _split_oversized_text(text: str, max_size: int) -> List[str]:
    """
    拆分超长文本，优先在句子边界切分

    先尝试使用 core.chunker.split_text_with_limit（如果可用），
    否则使用内置的句子边界拆分。

    Args:
        text: 待拆分文本
        max_size: 单片最大字符数

    Returns:
        拆分后的文本列表
    """
    if len(text) <= max_size:
        return [text]

    # 尝试使用 LangChain 分块器
    try:
        from core.chunker import split_text_with_limit
        result = split_text_with_limit(text, chunk_size=max_size, overlap=50, max_length=max_size)
        if result:
            return result
    except (ImportError, Exception):
        pass

    # 内置回退：按句子边界拆分
    import re
    sentences = re.split(r'(?<=[。！？.!?\n])', text)

    chunks = []
    current = ""

    for sentence in sentences:
        if not sentence:
            continue
        if len(current) + len(sentence) <= max_size:
            current += sentence
        else:
            if current:
                chunks.append(current)
            # 单句超长则硬截断
            if len(sentence) > max_size:
                for i in range(0, len(sentence), max_size):
                    chunks.append(sentence[i:i + max_size])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:max_size]]


def convert_to_rag_format(
    result: Dict[str, Any],
    source_file: str
) -> List[Dict]:
    """
    将 MinerU 结果转换为 RAG 入库格式

    Args:
        result: parse_with_mineru() 返回结果
        source_file: 源文件名

    Returns:
        [{'text': ..., 'page': ..., 'has_table': ..., ...}, ...]
    """
    pages_content = []

    for chunk in result['chunks']:
        # 跳过空内容
        content = chunk.content
        # content 可能是字符串或列表
        if isinstance(content, list):
            content = '\n'.join(str(item) for item in content)
        if not content or not content.strip():
            continue

        # 构建内容文本（基于已处理的 content）
        if chunk.chunk_type == "table" and chunk.table_html:
            # 表格：将 HTML 转为 Markdown 格式
            content = f"【表格】{chunk.title}\n\n{html_table_to_markdown(chunk.table_html)}"
        elif chunk.chunk_type == "image":
            content = f"【图片】{chunk.title}"
        elif chunk.chunk_type == "equation":
            content = f"【公式】{content}"
        elif chunk.text_level > 0:
            # 标题
            prefix = "#" * chunk.text_level
            content = f"{prefix} {content}"

        page_info = {
            'text': content,
            'page': chunk.page_start,
            'page_end': chunk.page_end,
            'has_table': chunk.chunk_type == "table",
            'section': chunk.title,
            'section_path': chunk.section_path,
            'level': chunk.text_level,
            'chunk_type': chunk.chunk_type,
            'source_file': source_file,
            'is_mineru_chunk': True  # 标记为 MinerU 输出
        }

        if chunk.bbox:
            # 确保 bbox 是纯 Python 列表（转换 numpy 类型）
            page_info['bbox'] = [float(x) for x in chunk.bbox] if chunk.bbox else None

        pages_content.append(page_info)

    return pages_content


def html_table_to_markdown(html_table: str) -> str:
    """
    将 HTML 表格转换为 Markdown 格式

    简单实现，仅处理基本表格结构
    """
    import re

    # 提取所有行
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_table, re.DOTALL)

    if not rows:
        return html_table

    md_rows = []
    for i, row in enumerate(rows):
        # 提取单元格
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
        # 清理 HTML 标签
        cells = [re.sub(r'<[^>]+>', '', cell).strip() for cell in cells]

        if cells:
            md_row = "| " + " | ".join(cells) + " |"
            md_rows.append(md_row)

            # 第一行后添加分隔线
            if i == 0:
                separator = "| " + " | ".join(["---"] * len(cells)) + " |"
                md_rows.append(separator)

    return "\n".join(md_rows)


# ========== 工具函数 ==========

def compute_file_hash(file_path: str) -> str:
    """
    计算文件 MD5 Hash，用于隔离输出目录

    Args:
        file_path: 文件路径

    Returns:
        12 位 hash 字符串
    """
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()[:12]


def parse_with_mineru_persistent(
    file_path: str,
    output_base: str = ".data/mineru_temp",
    images_output: str = ".data/images",
    lang: str = "ch",
    enable_table: bool = True,
    enable_formula: bool = True,
    backend: str = "pipeline",
    start_page: int = 0,
    end_page: int = 99999,
    cleanup_after_image_move: bool = True
) -> Dict[str, Any]:
    """
    使用 MinerU 解析文档（扁平化存储）

    用于分步流水线架构：
    - Step 1 (parse.py): 本地 GPU 运行 MinerU，输出持久化
    - Step 2 (embed.py): 读取 JSON，调用远端 API 生成摘要/描述

    Args:
        file_path: 文档文件路径
        output_base: MinerU 临时输出目录，默认 .data/mineru_temp（解析后自动清理）
        images_output: 图片存储目录，默认 .data/images（扁平化）
        lang: 语言代码 (ch, en, etc.)
        enable_table: 启用表格识别
        enable_formula: 启用公式识别
        backend: 解析后端 ("pipeline", "vlm-auto-engine", "hybrid-auto-engine")
        start_page: 起始页码（0-indexed，仅 PDF 有效）
        end_page: 结束页码（仅 PDF 有效）
        cleanup_after_image_move: 图片移动后是否清理临时输出（默认 True）

    Returns:
        {
            'markdown': str,           # Markdown 内容
            'chunks': List[MinerUChunk],  # 结构化分块
            'tables': List[str],       # 表格列表
            'images': List[str],       # 图片列表（已更新为最终路径）
            'content_list': List[Dict],# 原始 content_list
            'output_dir': str,         # MinerU 输出目录
            'file_hash': str           # 文件 hash
        }
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 计算文件 hash，用于隔离输出目录
    file_hash = compute_file_hash(str(file_path))
    output_dir = Path(output_base) / file_hash

    # 清理已存在的输出目录，避免权限冲突
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)

    # 调用核心解析函数
    result = parse_with_mineru(
        file_path=str(file_path),
        output_dir=str(output_dir),
        lang=lang,
        enable_table=enable_table,
        enable_formula=enable_formula,
        backend=backend,
        start_page=start_page,
        end_page=end_page
    )

    # 移动图片到统一存储目录
    # 即使 result['images'] 为空，也要检查 images 目录（处理嵌入表格的图片）
    images_dir = Path(images_output)
    images_dir.mkdir(parents=True, exist_ok=True)

    # 获取 MinerU 输出的图片源目录
    doc_name = file_path.stem
    auto_dir = output_dir / doc_name / "auto"
    office_dir = output_dir / doc_name / "office"

    if auto_dir.exists():
        img_src_dir = auto_dir / "images"
    elif office_dir.exists():
        img_src_dir = office_dir / "images"
    else:
        img_src_dir = None

    # 图片路径映射：旧路径 -> 新文件名
    image_path_map = {}  # { "images/abc.jpg": "0569dd285537.jpg" }

    # 首先处理 content_list.json 中引用的图片
    for img_path in result['images']:
        # img_path 是相对路径，如 "images/abc123.jpg"
        if img_src_dir:
            src_path = img_src_dir.parent / img_path  # 完整源路径
            if src_path.exists():
                # 计算 hash 避免冲突
                img_hash = compute_file_hash(str(src_path))
                new_name = f"{img_hash}{src_path.suffix}"
                dst_path = images_dir / new_name

                # 移动图片
                shutil.move(str(src_path), str(dst_path))
                # 记录映射：旧路径 -> 新文件名（只存文件名，不含目录）
                image_path_map[img_path] = new_name
                logger.debug(f"移动图片: {src_path} -> {dst_path}")
            else:
                # 源文件不存在，记录警告
                logger.warning(f"图片源文件不存在: {src_path}")
        else:
            logger.warning(f"图片源目录不存在，无法移动: {img_path}")

    # 扫描 images 目录中所有剩余图片（处理不在 content_list.json 中的图片）
    # 这些图片可能是嵌入表格中的图片，MinerU 没有在 content_list.json 中记录
    if img_src_dir and img_src_dir.exists():
        for img_file in img_src_dir.iterdir():
            if img_file.suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}:
                # 计算 hash 并移动
                img_hash = compute_file_hash(str(img_file))
                new_name = f"{img_hash}{img_file.suffix}"
                dst_path = images_dir / new_name

                shutil.move(str(img_file), str(dst_path))
                # 记录映射（使用相对路径作为 key）
                rel_path = f"images/{img_file.name}"
                image_path_map[rel_path] = new_name
                logger.debug(f"移动额外图片: {img_file} -> {dst_path}")

    # 更新 chunks 中的图片路径（单一来源：只在这里写路径）
    for chunk in result['chunks']:
        # 更新所有类型切片的 image_path（包括 table）
        if hasattr(chunk, 'image_path') and chunk.image_path:
            # 使用映射表更新为新文件名
            if chunk.image_path in image_path_map:
                chunk.image_path = image_path_map[chunk.image_path]
            else:
                # 兼容：尝试直接匹配文件名
                basename = os.path.basename(chunk.image_path)
                for old_path, new_name in image_path_map.items():
                    if basename in old_path:
                        chunk.image_path = new_name
                        break

    # 更新结果中的图片路径列表（供外部使用）
    result['images'] = list(image_path_map.values())

    # 清理 MinerU 输出目录（如果请求）
    if cleanup_after_image_move and output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
        logger.info(f"已清理 MinerU 输出目录: {output_dir}")

    # 添加额外元数据
    result['output_dir'] = str(output_dir)
    result['file_hash'] = file_hash

    return result


# ========== 格式特定别名 ==========

def parse_pdf_with_mineru(*args, **kwargs) -> Dict[str, Any]:
    """PDF 解析别名"""
    return parse_with_mineru(*args, **kwargs)


def parse_docx_with_mineru(*args, **kwargs) -> Dict[str, Any]:
    """Word 文档解析别名"""
    return parse_with_mineru(*args, **kwargs)


def parse_xlsx_with_mineru(*args, **kwargs) -> Dict[str, Any]:
    """Excel 解析别名"""
    return parse_with_mineru(*args, **kwargs)


def parse_pptx_with_mineru(*args, **kwargs) -> Dict[str, Any]:
    """PowerPoint 解析别名"""
    return parse_with_mineru(*args, **kwargs)


# ========== 兼容性别名 ==========

# 提供与旧 pdf_odl 模块兼容的接口
ChunkMetadata = MinerUChunk


if __name__ == "__main__":
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("用法: python mineru_parser.py <文件路径>")
        print(f"支持格式: {', '.join(SUPPORTED_FORMATS.keys())}")
        sys.exit(1)

    file_path = sys.argv[1]

    print(f"正在解析: {file_path}")
    result = parse_with_mineru(file_path)

    print(f"\n解析完成:")
    print(f"- Markdown 长度: {len(result['markdown'])} 字符")
    print(f"- 分块数量: {len(result['chunks'])}")
    print(f"- 表格数量: {len(result['tables'])}")
    print(f"- 图片数量: {len(result['images'])}")

    # 显示前几个分块
    print("\n前 5 个分块:")
    for i, chunk in enumerate(result['chunks'][:5]):
        print(f"\n--- Chunk {i+1} ({chunk.chunk_type}) ---")
        print(f"页码: {chunk.page_start}")
        print(f"标题: {chunk.title}")
        print(f"章节: {chunk.section_path}")
        print(chunk.content[:100] + "..." if len(chunk.content) > 100 else chunk.content)
