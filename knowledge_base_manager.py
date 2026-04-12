"""
⚠️ 此文件已迁移至 knowledge/manager.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from knowledge.manager import KnowledgeBaseManager, get_kb_manager
"""
import warnings as _warnings
_warnings.warn(
    "knowledge_base_manager 模块已迁移至 knowledge.manager，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from knowledge.manager import *  # noqa: F401,F403
