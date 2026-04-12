"""
⚠️ 此文件已迁移至 knowledge/sync.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from knowledge.sync import KnowledgeSyncService, SyncStatus, ChangeType
"""
import warnings as _warnings
_warnings.warn(
    "knowledge_sync 模块已迁移至 knowledge.sync，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from knowledge.sync import *  # noqa: F401,F403
