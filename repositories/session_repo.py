"""
会话存储接口

定义会话管理的抽象接口，支持不同的存储实现。
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class BaseSessionRepo(ABC):
    """会话存储接口"""

    @abstractmethod
    def get_history(self, session_id: str) -> List[Dict]:
        """
        获取会话历史

        Args:
            session_id: 会话ID

        Returns:
            消息列表，每条消息包含 role 和 content
        """
        pass

    @abstractmethod
    def add_message(self, session_id: str, role: str, content: str) -> None:
        """
        添加消息到会话

        Args:
            session_id: 会话ID
            role: 角色（user/assistant）
            content: 消息内容
        """
        pass

    @abstractmethod
    def create_session(self, user_id: str, title: str = "新对话") -> str:
        """
        创建新会话

        Args:
            user_id: 用户ID
            title: 会话标题

        Returns:
            会话ID
        """
        pass

    @abstractmethod
    def get_user_sessions(self, user_id: str) -> List[Dict]:
        """
        获取用户的会话列表

        Args:
            user_id: 用户ID

        Returns:
            会话列表
        """
        pass
