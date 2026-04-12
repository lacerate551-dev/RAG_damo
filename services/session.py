"""
会话管理器 - 支持多用户对话历史

功能：
1. 多用户会话隔离
2. 对话历史持久化（SQLite）
3. 历史压缩（避免上下文过长）
4. 会话过期清理

使用方式：
    from services.session import SessionManager

    sm = SessionManager()
    session_id = sm.create_session("user_123")

    # 添加对话
    sm.add_message(session_id, "user", "出差补助标准是什么？")
    sm.add_message(session_id, "assistant", "根据规定...")

    # 获取历史
    history = sm.get_history(session_id)

    # 生成带历史的提示词
    context = sm.build_context(session_id, "那请假呢？")
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import uuid


class SessionManager:
    """会话管理器"""

    def __init__(self, db_path: str = "./data/sessions.db", session_expire_hours: int = 24):
        """
        初始化会话管理器

        Args:
            db_path: SQLite数据库路径
            session_expire_hours: 会话过期时间（小时）
        """
        self.db_path = db_path
        self.session_expire_hours = session_expire_hours
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 会话表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        ''')

        # 消息历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        ''')

        # 创建索引加速查询
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sessions_user
            ON sessions(user_id)
        ''')

        conn.commit()
        conn.close()

    def create_session(self, user_id: str, metadata: dict = None) -> str:
        """
        创建新会话

        Args:
            user_id: 用户ID
            metadata: 可选的元数据（如用户名、IP等）

        Returns:
            session_id: 会话ID
        """
        session_id = str(uuid.uuid4())

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sessions (session_id, user_id, metadata)
            VALUES (?, ?, ?)
        ''', (session_id, user_id, json.dumps(metadata or {})))

        conn.commit()
        conn.close()

        return session_id

    def get_or_create_session(self, user_id: str, session_id: str = None) -> str:
        """
        获取或创建会话

        Args:
            user_id: 用户ID
            session_id: 可选的会话ID，如果提供则验证归属

        Returns:
            session_id: 有效会话ID
        """
        if session_id:
            # 验证会话是否存在且属于该用户
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT session_id FROM sessions
                WHERE session_id = ? AND user_id = ?
            ''', (session_id, user_id))

            result = cursor.fetchone()
            conn.close()

            if result:
                # 更新最后活跃时间
                self._update_last_active(session_id)
                return session_id

        # 创建新会话
        return self.create_session(user_id)

    def _update_last_active(self, session_id: str):
        """更新会话最后活跃时间"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE sessions
            SET last_active = CURRENT_TIMESTAMP
            WHERE session_id = ?
        ''', (session_id,))

        conn.commit()
        conn.close()

    def add_message(self, session_id: str, role: str, content: str):
        """
        添加消息到会话历史

        Args:
            session_id: 会话ID
            role: 角色 (user/assistant)
            content: 消息内容
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO messages (session_id, role, content)
            VALUES (?, ?, ?)
        ''', (session_id, role, content))

        # 更新会话活跃时间
        cursor.execute('''
            UPDATE sessions
            SET last_active = CURRENT_TIMESTAMP
            WHERE session_id = ?
        ''', (session_id,))

        conn.commit()
        conn.close()

    def get_history(self, session_id: str, limit: int = 20) -> List[Dict]:
        """
        获取会话历史

        Args:
            session_id: 会话ID
            limit: 最大消息数

        Returns:
            [{"role": "user/assistant", "content": "..."}, ...]
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT role, content, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (session_id, limit))

        rows = cursor.fetchall()
        conn.close()

        # 按时间正序排列（旧的在前）
        history = []
        for row in reversed(rows):
            history.append({
                "role": row[0],
                "content": row[1],
                "created_at": row[2]
            })

        return history

    def get_history_text(self, session_id: str, limit: int = 10) -> str:
        """
        获取历史文本格式（用于Prompt）

        Args:
            session_id: 会话ID
            limit: 最大轮次（一问一答为一轮）

        Returns:
            格式化的历史文本
        """
        history = self.get_history(session_id, limit=limit * 2)

        if not history:
            return ""

        lines = []
        for msg in history:
            role_name = "用户" if msg["role"] == "user" else "助手"
            lines.append(f"{role_name}：{msg['content']}")

        return "\n".join(lines)

    def build_context(self, session_id: str, current_query: str,
                      max_history_tokens: int = 1500) -> str:
        """
        构建带历史的上下文（智能压缩）

        Args:
            session_id: 会话ID
            current_query: 当前问题
            max_history_tokens: 历史最大token数（估算）

        Returns:
            包含历史的上下文文本
        """
        history = self.get_history(session_id, limit=20)

        if not history:
            return current_query

        # 构建历史摘要
        history_text = self._compress_history(history, max_history_tokens)

        context = f"""【对话历史】
{history_text}

【当前问题】
{current_query}"""

        return context

    def _compress_history(self, history: List[Dict], max_tokens: int) -> str:
        """
        压缩历史（避免上下文过长）

        策略：
        1. 保留最近的完整对话
        2. 较早的对话进行摘要压缩
        """
        # 简单估算：1个中文字约等于1.5个token
        def estimate_tokens(text: str) -> int:
            return len(text) * 1.5

        # 从最新开始，保留尽可能多的完整对话
        selected = []
        total_tokens = 0

        for msg in reversed(history):
            msg_tokens = estimate_tokens(msg["content"])

            if total_tokens + msg_tokens > max_tokens:
                # 超出限制，停止
                break

            selected.insert(0, msg)
            total_tokens += msg_tokens

        if not selected:
            return ""

        # 如果有更早的历史被省略，添加提示
        if len(selected) < len(history):
            omitted_count = len(history) - len(selected)
            prefix = f"[省略了 {omitted_count} 条较早的历史消息]\n\n"
        else:
            prefix = ""

        # 格式化
        lines = []
        for msg in selected:
            role_name = "用户" if msg["role"] == "user" else "助手"
            lines.append(f"{role_name}：{msg['content']}")

        return prefix + "\n".join(lines)

    def clear_history(self, session_id: str):
        """清空会话历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM messages WHERE session_id = ?
        ''', (session_id,))

        conn.commit()
        conn.close()

    def delete_session(self, session_id: str):
        """删除会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM messages WHERE session_id = ?
        ''', (session_id,))

        cursor.execute('''
            DELETE FROM sessions WHERE session_id = ?
        ''', (session_id,))

        conn.commit()
        conn.close()

    def cleanup_expired_sessions(self):
        """清理过期会话"""
        expire_time = datetime.now() - timedelta(hours=self.session_expire_hours)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 删除过期会话的消息
        cursor.execute('''
            DELETE FROM messages
            WHERE session_id IN (
                SELECT session_id FROM sessions
                WHERE last_active < ?
            )
        ''', (expire_time,))

        # 删除过期会话
        cursor.execute('''
            DELETE FROM sessions
            WHERE last_active < ?
        ''', (expire_time,))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted

    def get_user_sessions(self, user_id: str, limit: int = 10) -> List[Dict]:
        """
        获取用户的所有会话

        Returns:
            [{"session_id": "...", "created_at": "...", "last_active": "..."}, ...]
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT session_id, created_at, last_active, metadata
            FROM sessions
            WHERE user_id = ?
            ORDER BY last_active DESC
            LIMIT ?
        ''', (user_id, limit))

        rows = cursor.fetchall()
        conn.close()

        sessions = []
        for row in rows:
            sessions.append({
                "session_id": row[0],
                "created_at": row[1],
                "last_active": row[2],
                "metadata": json.loads(row[3]) if row[3] else {}
            })

        return sessions

    def get_stats(self) -> Dict:
        """获取统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM sessions')
        total_sessions = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM messages')
        total_messages = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM sessions')
        total_users = cursor.fetchone()[0]

        conn.close()

        return {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_users": total_users
        }


# 测试代码
if __name__ == "__main__":
    # 创建会话管理器
    sm = SessionManager()

    print("=" * 50)
    print("会话管理器测试")
    print("=" * 50)

    # 测试1: 创建会话
    print("\n【测试1】创建会话")
    user_id = "test_user_001"
    session_id = sm.create_session(user_id, {"name": "测试用户"})
    print(f"用户ID: {user_id}")
    print(f"会话ID: {session_id}")

    # 测试2: 添加对话
    print("\n【测试2】添加对话")
    sm.add_message(session_id, "user", "出差补助标准是什么？")
    sm.add_message(session_id, "assistant", "根据公司规定，出差补助包括伙食费、交通费和住宿费。伙食补助每天100元...")
    sm.add_message(session_id, "user", "那请假流程呢？")
    sm.add_message(session_id, "assistant", "请假流程如下：1. 提交请假申请...")

    print("已添加4条消息")

    # 测试3: 获取历史
    print("\n【测试3】获取历史")
    history = sm.get_history(session_id)
    for msg in history:
        role = "用户" if msg["role"] == "user" else "助手"
        print(f"  {role}: {msg['content'][:30]}...")

    # 测试4: 构建上下文
    print("\n【测试4】构建上下文")
    context = sm.build_context(session_id, "婚假有多少天？")
    print(context)

    # 测试5: 统计信息
    print("\n【测试5】统计信息")
    stats = sm.get_stats()
    print(f"  总会话数: {stats['total_sessions']}")
    print(f"  总消息数: {stats['total_messages']}")
    print(f"  总用户数: {stats['total_users']}")

    # 测试6: 获取用户会话列表
    print("\n【测试6】用户会话列表")
    sessions = sm.get_user_sessions(user_id)
    for s in sessions:
        print(f"  会话ID: {s['session_id'][:8]}...")
        print(f"  创建时间: {s['created_at']}")
        print(f"  最后活跃: {s['last_active']}")

    print("\n" + "=" * 50)
    print("测试完成")
