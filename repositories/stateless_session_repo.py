"""
无状态会话存储实现（生产环境）

生产环境不存储会话数据，历史由后端传入。
"""

from .session_repo import BaseSessionRepo
from typing import List, Dict, Optional


class StatelessSessionRepo(BaseSessionRepo):
    """生产环境：无状态，不存储"""

    def get_history(self, session_id: str) -> List[Dict]:
        """生产环境：历史由后端传入，不查询"""
        return []

    def add_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """生产环境：不存储消息"""
        pass

    def create_session(self, user_id: str, title: str = "新对话") -> str:
        """生产环境：不创建会话，返回占位符"""
        return "stateless"

    def get_user_sessions(self, user_id: str) -> List[Dict]:
        """生产环境：会话列表由后端管理"""
        return []
