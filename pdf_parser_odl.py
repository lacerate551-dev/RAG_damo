"""
⚠️ 此文件已迁移至 parsers/pdf_odl.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from parsers.pdf_odl import parse_pdf_with_odl, ChunkMetadata
"""
import warnings as _warnings
_warnings.warn(
    "pdf_parser_odl 模块已迁移至 parsers.pdf_odl，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from parsers.pdf_odl import *  # noqa: F401,F403
