"""
⚠️ 此文件已迁移至 services/session.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from services.session import SessionManager
"""
import warnings as _warnings
_warnings.warn(
    "session_manager 模块已迁移至 services.session，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from services.session import *  # noqa: F401,F403
