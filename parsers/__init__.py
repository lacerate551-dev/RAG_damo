# -*- coding: utf-8 -*-
"""
文档解析器模块 (v5 - MinerU 统一版)

统一入口：parse_document(filepath) -> List[UnifiedChunk]

格式支持：
- PDF/DOCX/PPTX/图片 → parse_with_mineru_persistent()
- XLSX/XLS → parse_excel() (Pandas 专属管道)
- TXT → parse_txt()

MinerU 3.0+ 优势：
- PDF: 表格识别率 95%+，支持 109 种语言 OCR
- DOCX: 原生解析，速度提升数十倍，无幻觉
- 图片自动提取，路径存入 UnifiedChunk

依赖：
    pip install "mineru[all]"
    pip install pandas openpyxl
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# ========== 支持的文件格式 ==========

SUPPORTED_FORMATS = {
    # MinerU 支持
    '.pdf': 'PDF 文档',
    '.docx': 'Word 文档',
    '.pptx': 'PowerPoint 幻灯片',
    '.png': 'PNG 图片',
    '.jpg': 'JPEG 图片',
    '.jpeg': 'JPEG 图片',
    '.bmp': 'BMP 图片',
    '.tiff': 'TIFF 图片',
    # Pandas 支持
    '.xlsx': 'Excel 表格',
    '.xls': 'Excel 表格',
    # 文本
    '.txt': '文本文件',
}

# ========== 模块可用性检测 ==========

MINERU_AVAILABLE = False
PANDAS_AVAILABLE = False

try:
    from parsers.mineru_parser import (
        parse_with_mineru_persistent,
        parse_with_mineru,
        MinerUChunk,
        convert_to_rag_format as mineru_to_rag_format,
    )
    MINERU_AVAILABLE = True
except ImportError as e:
    logger.warning(f"MinerU 不可用: {e}")

try:
    from parsers.excel_parser import (
        parse_excel,
        get_table_meta,
        convert_to_rag_format as excel_to_rag_format,
        UnifiedChunk as ExcelChunk,
    )
    PANDAS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Excel 解析器不可用: {e}")

try:
    from parsers.txt_parser import extract_text_from_txt
    TXT_AVAILABLE = True
except ImportError:
    TXT_AVAILABLE = False


# ========== 统一 Schema ==========

@dataclass
class UnifiedChunk:
    """
    统一内部 Schema - 所有解析器输出此格式

    与 MinerUChunk 完全兼容，方便下游处理。
    """
    content: str                      # 文本内容（Markdown 格式）
    chunk_type: str                   # 类型: text, table, image, equation
    page_start: int = 1               # 起始页码/行号
    page_end: int = 1                 # 结束页码/行号
    text_level: int = 0               # 标题级别 (0=body, 1=h1, ...)
    title: str = ""                   # 标题文本
    section_path: str = ""            # 章节路径
    source_file: str = ""             # 源文件名
    bbox: Optional[List[float]] = None  # 边界框 [x0, y0, x1, y1]
    table_html: Optional[str] = None  # 表格 HTML（表格类型）
    image_path: Optional[str] = None  # 图片路径（图片类型）


class UnsupportedFormatError(Exception):
    """不支持的文件格式异常"""
    pass


# ========== 统一入口函数 ==========

def parse_document(
    filepath: str,
    output_base: str = ".data/mineru_temp",
    images_output: str = ".data/images",
    **kwargs
) -> Dict[str, Any]:
    """
    统一文档解析入口（扁平化存储）

    Args:
        filepath: 文档文件路径
        output_base: MinerU 临时输出目录
        images_output: 图片存储目录
        **kwargs: 格式特定参数

    Returns:
        {
            'chunks': List[UnifiedChunk],  # 结构化分块
            'markdown': str,               # Markdown 内容
            'tables': List[str],           # 表格列表
            'images': List[str],           # 图片列表
            'source_file': str,            # 源文件名
            'parser_used': str,            # 使用的解析器
        }

    Raises:
        UnsupportedFormatError: 不支持的文件格式
        FileNotFoundError: 文件不存在
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(
            f"不支持的文件格式: {ext}。"
            f"支持格式: {', '.join(SUPPORTED_FORMATS.keys())}"
        )

    logger.info(f"解析 {SUPPORTED_FORMATS.get(ext, '文档')}: {filepath.name}")

    # 根据扩展名选择解析器
    if ext in ('.pdf', '.docx', '.pptx', '.png', '.jpg', '.jpeg', '.bmp', '.tiff'):
        return _parse_with_mineru(filepath, output_base, images_output, **kwargs)
    elif ext in ('.xlsx', '.xls'):
        return _parse_with_pandas(filepath, **kwargs)
    elif ext == '.txt':
        return _parse_txt(filepath, **kwargs)
    else:
        raise UnsupportedFormatError(f"不支持的文件格式: {ext}")


def _parse_with_mineru(
    filepath: Path,
    output_base: str,
    images_output: str,
    **kwargs
) -> Dict[str, Any]:
    """使用 MinerU 解析文档"""
    if not MINERU_AVAILABLE:
        raise RuntimeError("MinerU 不可用，请运行: pip install \"mineru[all]\"")

    result = parse_with_mineru_persistent(
        str(filepath),
        output_base=output_base,
        images_output=images_output,
        cleanup_after_image_move=kwargs.get('cleanup_after_image_move', False)
    )

    # 转换 chunks 为 UnifiedChunk 格式（已是 MinerUChunk，兼容）
    chunks = result.get('chunks', [])

    return {
        'chunks': chunks,
        'markdown': result.get('markdown', ''),
        'tables': result.get('tables', []),
        'images': result.get('images', []),
        'source_file': filepath.name,
        'parser_used': 'mineru',
        'file_hash': result.get('file_hash', ''),
        'output_dir': result.get('output_dir', ''),
    }


def _parse_with_pandas(filepath: Path, **kwargs) -> Dict[str, Any]:
    """使用 Pandas 解析 Excel"""
    if not PANDAS_AVAILABLE:
        raise RuntimeError("Excel 解析器不可用，请运行: pip install pandas openpyxl")

    result = parse_excel(
        str(filepath),
        max_rows_per_chunk=kwargs.get('max_rows_per_chunk', 200)
    )

    # 转换 chunks 为 UnifiedChunk 格式（已是 UnifiedChunk）
    chunks = result.get('chunks', [])

    # 构建 Markdown
    markdown_parts = []
    for chunk in chunks:
        markdown_parts.append(f"## {chunk.title}\n\n{chunk.content}\n")

    return {
        'chunks': chunks,
        'markdown': "\n".join(markdown_parts),
        'tables': [chunk.content for chunk in chunks],
        'images': [],
        'source_file': filepath.name,
        'parser_used': 'pandas',
        'sheets': result.get('sheets', []),
        'total_rows': result.get('total_rows', 0),
    }


def _parse_txt(filepath: Path, **kwargs) -> Dict[str, Any]:
    """解析纯文本文件"""
    # 直接读取文件内容
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 简单分块
    chunk_size = kwargs.get('chunk_size', 1000)
    chunks = []

    for i in range(0, len(content), chunk_size):
        chunk_content = content[i:i+chunk_size]
        chunk = UnifiedChunk(
            content=chunk_content,
            chunk_type="text",
            page_start=i // chunk_size + 1,
            page_end=i // chunk_size + 1,
            source_file=filepath.name
        )
        chunks.append(chunk)

    return {
        'chunks': chunks,
        'markdown': content,
        'tables': [],
        'images': [],
        'source_file': filepath.name,
        'parser_used': 'txt',
    }


# ========== RAG 格式转换 ==========

def convert_to_rag_format(result: Dict[str, Any]) -> List[Dict]:
    """
    将解析结果转换为 RAG 入库格式

    Args:
        result: parse_document() 返回结果

    Returns:
        [{'text': ..., 'page': ..., 'has_table': ..., ...}, ...]
    """
    parser_used = result.get('parser_used', 'unknown')
    chunks = result.get('chunks', [])

    if parser_used == 'mineru':
        # MinerU chunks 已有专用转换函数
        from parsers.mineru_parser import convert_to_rag_format as mineru_convert
        return mineru_convert(result, result.get('source_file', ''))

    elif parser_used == 'pandas':
        # Excel chunks
        from parsers.excel_parser import convert_to_rag_format as excel_convert
        return excel_convert(result)

    else:
        # 通用转换
        pages_content = []
        for chunk in chunks:
            page_info = {
                'text': chunk.content,
                'page': chunk.page_start,
                'page_end': chunk.page_end,
                'has_table': chunk.chunk_type == 'table',
                'section': chunk.title,
                'section_path': chunk.section_path,
                'level': chunk.text_level,
                'chunk_type': chunk.chunk_type,
                'source_file': chunk.source_file,
            }
            pages_content.append(page_info)

        return pages_content


# ========== 兼容旧接口 ==========

def extract_text_from_pdf(filepath, **kwargs):
    """兼容旧接口：从 PDF 提取文本"""
    result = parse_document(filepath, **kwargs)
    pages_content = convert_to_rag_format(result)
    images_info = [{'id': img} for img in result.get('images', [])]
    return pages_content, images_info


def extract_text_from_docx(filepath, **kwargs):
    """兼容旧接口：从 Word 提取文本"""
    result = parse_document(filepath, **kwargs)
    return convert_to_rag_format(result)


def extract_text_from_xlsx(filepath, **kwargs):
    """兼容旧接口：从 Excel 提取文本"""
    result = parse_document(filepath, **kwargs)
    return convert_to_rag_format(result)


def extract_text_from_txt(filepath, **kwargs):
    """兼容旧接口：从 TXT 提取文本"""
    # 直接读取文件，避免递归调用 parse_document
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 简单分块
    chunk_size = kwargs.get('chunk_size', 1000)
    chunks = []
    for i in range(0, len(content), chunk_size):
        chunks.append({
            "content": content[i:i+chunk_size],
            "chunk_type": "text",
            "page": i // chunk_size + 1
        })

    return {
        "chunks": chunks,
        "markdown": content,
        "tables": [],
        "images": []
    }


# ========== 模块导出 ==========

__all__ = [
    # 统一入口
    'parse_document',
    'convert_to_rag_format',
    'UnifiedChunk',
    'UnsupportedFormatError',
    'SUPPORTED_FORMATS',
    # 兼容旧接口
    'extract_text_from_pdf',
    'extract_text_from_docx',
    'extract_text_from_xlsx',
    'extract_text_from_txt',
    # 可用性标志
    'MINERU_AVAILABLE',
    'PANDAS_AVAILABLE',
]
