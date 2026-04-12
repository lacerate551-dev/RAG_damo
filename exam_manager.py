"""
⚠️ 此文件已迁移至 exam_pkg/manager.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from exam_pkg.manager import generate_exam, save_exam, grade_exam, ...
"""
import warnings as _warnings
_warnings.warn(
    "exam_manager 模块已迁移至 exam_pkg.manager，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from exam_pkg.manager import *  # noqa: F401,F403
