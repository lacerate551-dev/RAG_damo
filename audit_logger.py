"""
⚠️ 此文件已迁移至 services/audit.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from services.audit import AuditLogger
"""
import warnings as _warnings
_warnings.warn(
    "audit_logger 模块已迁移至 services.audit，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from services.audit import *  # noqa: F401,F403
