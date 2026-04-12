"""
⚠️ 此文件已迁移至 parsers/excel_parser.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from parsers.excel_parser import ExcelParserEnhanced, ExcelChunk
"""
import warnings as _warnings
_warnings.warn(
    "excel_parser_enhanced 模块已迁移至 parsers.excel_parser，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from parsers.excel_parser import *  # noqa: F401,F403
