"""
SQLite 会话存储实现（开发环境）

使用本地 SQLite 数据库存储会话数据。
"""

from .session_repo import BaseSessionRepo
from typing import List, Dict
import uuid
from datetime import datetime


class SQLiteSessionRepo(BaseSessionRepo):
    """开发环境：SQLite存储"""

    def __init__(self):
        from data.db import get_connection
        self.get_connection = get_connection

    def get_history(self, session_id: str) -> List[Dict]:
        """获取会话历史"""
        with self.get_connection("core") as conn:
            cursor = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            )
            return [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """添加消息到会话"""
        with self.get_connection("core") as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.now().isoformat())
            )

    def update_last_active(self, session_id: str) -> None:
        """更新会话最后活跃时间"""
        with self.get_connection("core") as conn:
            conn.execute(
                "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                (datetime.now().isoformat(), session_id)
            )

    def create_session(self, user_id: str, title: str = "新对话") -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        with self.get_connection("core") as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, user_id, created_at, last_active) VALUES (?, ?, ?, ?)",
                (session_id, user_id, datetime.now().isoformat(), datetime.now().isoformat())
            )
        return session_id

    def get_user_sessions(self, user_id: str) -> List[Dict]:
        """获取用户的会话列表"""
        with self.get_connection("core") as conn:
            cursor = conn.execute(
                "SELECT session_id, created_at, last_active FROM sessions WHERE user_id = ? ORDER BY last_active DESC",
                (user_id,)
            )
            return [
                {
                    "session_id": row[0],
                    "title": "对话",  # 默认标题
                    "created_at": row[1],
                    "last_active": row[2]
                }
                for row in cursor.fetchall()
            ]
