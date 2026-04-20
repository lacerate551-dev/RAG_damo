"""
业务服务模块

包含：
- session: 会话管理（开发环境）
- feedback: 问答质量闭环（反馈、FAQ、质量报告）
- outline: 纲要生成与关联推荐
"""

from services.session import SessionManager

__all__ = [
    'SessionManager',
]
