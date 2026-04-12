"""
⚠️ 此文件已迁移至 knowledge/diff.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from knowledge.diff import ...
"""
import warnings as _warnings
_warnings.warn(
    "document_diff 模块已迁移至 knowledge.diff，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from knowledge.diff import *  # noqa: F401,F403
