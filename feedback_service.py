"""
⚠️ 此文件已迁移至 services/feedback.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from services.feedback import FeedbackDB, FeedbackService, Feedback, FAQ, QualityReport
"""
import warnings as _warnings
_warnings.warn(
    "feedback_service 模块已迁移至 services.feedback，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from services.feedback import *  # noqa: F401,F403
