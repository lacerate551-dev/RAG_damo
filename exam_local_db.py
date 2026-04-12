"""
⚠️ 此文件已迁移至 exam_pkg/local_db.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from exam_pkg.local_db import ...
"""
import warnings as _warnings
_warnings.warn(
    "exam_local_db 模块已迁移至 exam_pkg.local_db，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from exam_pkg.local_db import *  # noqa: F401,F403
