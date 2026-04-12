"""
⚠️ 此文件已迁移至 knowledge/lifecycle.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from knowledge.lifecycle import ...
"""
import warnings as _warnings
_warnings.warn(
    "document_lifecycle 模块已迁移至 knowledge.lifecycle，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from knowledge.lifecycle import *  # noqa: F401,F403
