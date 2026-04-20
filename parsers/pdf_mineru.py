# -*- coding: utf-8 -*-
"""
MinerU PDF 解析模块（兼容性别名）

此文件保留用于向后兼容，实际实现已迁移到 mineru_parser.py
新代码请直接使用: from parsers.mineru_parser import parse_with_mineru
"""

# 从新模块导入所有内容
from parsers.mineru_parser import (
    parse_with_mineru,
    parse_pdf_with_mineru,
    parse_docx_with_mineru,
    parse_xlsx_with_mineru,
    parse_pptx_with_mineru,
    convert_to_rag_format,
    html_table_to_markdown,
    MinerUChunk,
    ChunkMetadata,
    SUPPORTED_FORMATS,
)

# 保持向后兼容
__all__ = [
    'parse_pdf_with_mineru',
    'parse_with_mineru',
    'convert_to_rag_format',
    'html_table_to_markdown',
    'MinerUChunk',
    'ChunkMetadata',
]
