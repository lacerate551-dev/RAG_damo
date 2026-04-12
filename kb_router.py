"""
⚠️ 此文件已迁移至 knowledge/router.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from knowledge.router import KnowledgeBaseRouter, get_kb_router, route_query
"""
import warnings as _warnings
_warnings.warn(
    "kb_router 模块已迁移至 knowledge.router，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from knowledge.router import *  # noqa: F401,F403
