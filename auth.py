"""
用户认证模块 - JWT 认证与角色管理

功能：
1. 用户注册/登录
2. JWT Token 签发与验证
3. @require_auth 装饰器保护 API 端点
4. 基于角色的访问控制（RBAC）

角色体系：
- admin: 超级管理员，可访问所有文档，可管理用户
- manager: 管理层，可访问内部+公开文档
- user: 普通用户，可访问公开文档

使用方式：
    from auth import AuthManager, require_auth

    auth = AuthManager()

    # 在 Flask 路由中使用
    @app.route('/protected')
    @require_auth
    def protected():
        user = request.current_user  # {"user_id": ..., "role": ..., "department": ...}
        ...
"""

import sqlite3
import json
import os
import uuid
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from functools import wraps

import jwt
from flask import request, jsonify


class AuthManager:
    """用户认证管理器"""

    def __init__(self, db_path: str = "./sessions.db", jwt_secret: Optional[str] = None,
                 token_expire_hours: int = 24):
        self.db_path = db_path
        self.jwt_secret = jwt_secret or os.environ.get(
            "JWT_SECRET",
            "dev-secret-change-in-production"
        )
        self.token_expire_hours = token_expire_hours
        self._init_db()

    def _init_db(self):
        """初始化用户表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                department TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 角色权限表：定义每个角色可以访问的安全级别
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS role_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                allowed_levels TEXT NOT NULL,
                description TEXT,
                UNIQUE(role)
            )
        ''')

        # 创建索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_users_username
            ON users(username)
        ''')

        # 初始化默认角色权限
        cursor.execute("SELECT COUNT(*) FROM role_permissions")
        if cursor.fetchone()[0] == 0:
            default_permissions = [
                ("admin", json.dumps(["public", "internal", "confidential", "secret"]), "超级管理员，可访问所有文档"),
                ("manager", json.dumps(["public", "internal", "confidential"]), "管理层，可访问内部和机密文档"),
                ("user", json.dumps(["public", "internal"]), "普通用户，可访问公开和内部文档"),
            ]
            cursor.executemany(
                "INSERT INTO role_permissions (role, allowed_levels, description) VALUES (?, ?, ?)",
                default_permissions
            )

        # 创建默认管理员（仅首次）
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] == 0:
            self._create_user_internal(cursor, "admin", "admin123", "admin", "系统管理部")

        conn.commit()
        conn.close()

    @staticmethod
    def _hash_password(password: str) -> str:
        """密码哈希（使用 SHA-256 + salt）"""
        salt = uuid.uuid4().hex
        hash_val = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"{salt}:{hash_val}"

    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        """验证密码"""
        salt, stored_hash = password_hash.split(":", 1)
        hash_val = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(hash_val, stored_hash)

    def _create_user_internal(self, cursor, username: str, password: str,
                              role: str = "user", department: str = "") -> str:
        """内部创建用户（已有 cursor）"""
        user_id = str(uuid.uuid4())
        password_hash = self._hash_password(password)
        cursor.execute(
            "INSERT INTO users (user_id, username, password_hash, role, department) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, password_hash, role, department)
        )
        return user_id

    def create_user(self, username: str, password: str, role: str = "user",
                    department: str = "") -> Tuple[bool, str, Optional[str]]:
        """
        创建用户

        Returns:
            (success, message, user_id)
        """
        if not username or not password:
            return False, "用户名和密码不能为空", None

        if len(password) < 6:
            return False, "密码至少6位", None

        if role not in ("admin", "manager", "user"):
            return False, f"无效的角色: {role}", None

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            user_id = self._create_user_internal(cursor, username, password, role, department)
            conn.commit()
            return True, "用户创建成功", user_id
        except sqlite3.IntegrityError:
            return False, f"用户名 '{username}' 已存在", None
        finally:
            conn.close()

    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[Dict]]:
        """
        用户认证

        Returns:
            (success, user_info or None)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT user_id, username, password_hash, role, department, is_active FROM users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return False, None

        user_id, uname, pw_hash, role, department, is_active = row

        if not is_active:
            return False, None

        if not self._verify_password(password, pw_hash):
            return False, None

        return True, {
            "user_id": user_id,
            "username": uname,
            "role": role,
            "department": department
        }

    def generate_token(self, user_info: Dict) -> str:
        """生成 JWT Token"""
        payload = {
            "user_id": user_info["user_id"],
            "username": user_info["username"],
            "role": user_info["role"],
            "department": user_info["department"],
            "exp": datetime.utcnow() + timedelta(hours=self.token_expire_hours),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> Tuple[bool, Optional[Dict]]:
        """
        验证 JWT Token

        Returns:
            (valid, payload or None)
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return True, payload
        except jwt.ExpiredSignatureError:
            return False, None
        except jwt.InvalidTokenError:
            return False, None

    def get_user_permissions(self, role: str) -> List[str]:
        """获取角色对应的可访问安全级别"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT allowed_levels FROM role_permissions WHERE role = ?",
            (role,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return ["public"]

        return json.loads(row[0])

    def get_all_users(self) -> List[Dict]:
        """获取所有用户列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT user_id, username, role, department, is_active, created_at FROM users ORDER BY created_at"
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "user_id": r[0],
                "username": r[1],
                "role": r[2],
                "department": r[3],
                "is_active": bool(r[4]),
                "created_at": r[5]
            }
            for r in rows
        ]

    def update_user(self, user_id: str, role: Optional[str] = None,
                    department: Optional[str] = None,
                    is_active: Optional[bool] = None) -> bool:
        """更新用户信息"""
        updates = []
        params = []

        if role is not None:
            updates.append("role = ?")
            params.append(role)
        if department is not None:
            updates.append("department = ?")
            params.append(department)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(int(is_active))

        if not updates:
            return False

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(user_id)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)
        affected = cursor.rowcount
        conn.commit()
        conn.close()

        return affected > 0

    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def change_password(self, user_id: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        """修改密码"""
        if len(new_password) < 6:
            return False, "新密码至少6位"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT password_hash FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "用户不存在"

        if not self._verify_password(old_password, row[0]):
            conn.close()
            return False, "原密码错误"

        new_hash = self._hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_hash, user_id)
        )
        conn.commit()
        conn.close()
        return True, "密码修改成功"


# 全局认证管理器实例
_auth_manager: Optional[AuthManager] = None


def init_auth(app=None, db_path: str = "./sessions.db", jwt_secret: Optional[str] = None):
    """初始化认证模块"""
    global _auth_manager
    _auth_manager = AuthManager(db_path=db_path, jwt_secret=jwt_secret)
    return _auth_manager


def get_auth_manager() -> AuthManager:
    """获取认证管理器实例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def require_auth(f):
    """
    认证装饰器 - 保护 API 端点

    使用方式：
        @app.route('/protected')
        @require_auth
        def protected():
            user = request.current_user
            return jsonify({"user_id": user["user_id"]})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            return jsonify({"error": "缺少认证令牌，请先登录"}), 401

        token = auth_header[7:]
        manager = get_auth_manager()
        valid, payload = manager.verify_token(token)

        if not valid:
            return jsonify({"error": "认证令牌无效或已过期"}), 401

        # 将用户信息附加到 request 对象
        request.current_user = payload
        return f(*args, **kwargs)

    return decorated


def require_role(*roles):
    """
    角色验证装饰器 - 需要指定角色才能访问

    使用方式：
        @app.route('/admin')
        @require_auth
        @require_role('admin')
        def admin_only():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(request, 'current_user', None)
            if not user:
                return jsonify({"error": "请先认证"}), 401

            if user.get('role') not in roles:
                return jsonify({"error": "权限不足"}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator
