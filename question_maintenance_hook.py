"""
⚠️ 此文件已迁移至 exam_pkg/question_hook.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from exam_pkg.question_hook import ...
"""
import warnings as _warnings
_warnings.warn(
    "question_maintenance_hook 模块已迁移至 exam_pkg.question_hook，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from exam_pkg.question_hook import *  # noqa: F401,F403
