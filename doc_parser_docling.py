"""
⚠️ 此文件已迁移至 parsers/docx_docling.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from parsers.docx_docling import DoclingParser, DOCLING_AVAILABLE, DocChunk
"""
import warnings as _warnings
_warnings.warn(
    "doc_parser_docling 模块已迁移至 parsers.docx_docling，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from parsers.docx_docling import *  # noqa: F401,F403
