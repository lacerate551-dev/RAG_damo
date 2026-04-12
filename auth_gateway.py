"""
⚠️ 此文件已迁移至 auth/gateway.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from auth.gateway import require_gateway_auth, require_role, get_user_permissions
"""
import warnings as _warnings
_warnings.warn(
    "auth_gateway 模块已迁移至 auth.gateway，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from auth.gateway import *  # noqa: F401,F403
