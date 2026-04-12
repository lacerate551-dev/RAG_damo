"""
⚠️ 此文件已迁移至 auth/security.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from auth.security import validate_query, sanitize_user_input, filter_response, AgentConstraints
"""
import warnings as _warnings
_warnings.warn(
    "security 模块已迁移至 auth.security，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from auth.security import *  # noqa: F401,F403
