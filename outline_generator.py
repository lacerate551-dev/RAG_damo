"""
⚠️ 此文件已迁移至 services/outline.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from services.outline import OutlineDB, OutlineGenerator, RecommendationService
"""
import warnings as _warnings
_warnings.warn(
    "outline_generator 模块已迁移至 services.outline，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from services.outline import *  # noqa: F401,F403
