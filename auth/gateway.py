"""
网关认证模块 - 从网关注入的 Header 读取用户信息

## 使用方式

    from auth.gateway import require_gateway_auth, get_current_user

    @app.route('/protected')
    @require_gateway_auth
    def protected():
        user = request.current_user  # {"user_id": ..., "role": ..., ...}
        ...

## Header 规范（开发模式可选）

    - X-User-ID: 用户唯一标识 (可选)
    - X-User-Name: 用户名 (可选)
    - X-User-Role: 用户角色 (可选)
    - X-User-Department: 部门 (可选)

## 模式说明

开发模式 (DEV_MODE=true，默认):
- 支持 mock token 模拟用户：Authorization: Bearer mock-token-admin
- 无 Header 时自动使用开发测试用户
- 适用于前端测试和开发调试

生产模式 (DEV_MODE=false):
- 不需要 Header，直接放行
- 权限由后端完全控制，通过 collections 参数传入
- RAG 服务完全无状态，只负责问答检索
"""

from functools import wraps
from flask import request, jsonify
from typing import Dict, Optional
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录）
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


# ==================== 模拟用户数据（开发环境）====================
# 用于前端模拟登录测试，仅 DEV_MODE=true 时生效
MOCK_USERS = {
    'admin': {
        'user_id': 'admin001',
        'password': 'admin123',
        'role': 'admin',
        'department': '管理部'
    },
    'admin2': {
        'user_id': 'admin002',
        'password': 'admin456',
        'role': 'admin',
        'department': '技术部'
    },
    'admin3': {
        'user_id': 'admin003',
        'password': 'admin789',
        'role': 'admin',
        'department': '运营部'
    },
    'manager': {
        'user_id': 'manager001',
        'password': 'manager123',
        'role': 'manager',
        'department': '财务部'
    },
    'user': {
        'user_id': 'user001',
        'password': 'test123',
        'role': 'user',
        'department': '技术部'
    }
}


def require_gateway_auth(f):
    """
    网关认证装饰器 - 从 Header 读取用户信息

    开发模式 (DEV_MODE=true，默认):
    - 支持 mock token: Authorization: Bearer mock-token-admin
    - 无 Header 时自动使用开发测试用户（admin 角色）

    生产模式 (DEV_MODE=false):
    - 不需要 Header，直接放行
    - 用户信息设为默认值
    - 权限由后端通过 collections 参数控制
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # 开发模式开关（默认开启，生产环境设置 DEV_MODE=false）
        dev_mode = os.environ.get('DEV_MODE', 'true').lower() != 'false'

        # 开发模式：支持 mock token
        if dev_mode:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer mock-token-'):
                username = auth_header.replace('Bearer mock-token-', '')
                mock_user = MOCK_USERS.get(username)
                if mock_user:
                    request.current_user = {
                        "user_id": mock_user['user_id'],
                        "username": username,
                        "role": mock_user['role'],
                        "department": mock_user['department']
                    }
                    return f(*args, **kwargs)

        # 从 Header 读取用户信息（可选）
        user_id = request.headers.get('X-User-ID')
        username = request.headers.get('X-User-Name', '')
        role = request.headers.get('X-User-Role', 'user')
        department = request.headers.get('X-User-Department', '')

        # 如果有 Header，使用 Header 中的用户信息
        if user_id:
            request.current_user = {
                "user_id": user_id,
                "username": username,
                "role": role,
                "department": department
            }
            return f(*args, **kwargs)

        # 无 Header 时的默认处理
        if dev_mode:
            # 开发模式：使用默认测试用户
            request.current_user = {
                "user_id": "dev-user",
                "username": "开发测试用户",
                "role": "admin",
                "department": "开发部"
            }
        else:
            # 生产模式：使用默认用户（后端通过 collections 控制权限）
            request.current_user = {
                "user_id": "backend-caller",
                "username": "后端调用",
                "role": "user",
                "department": ""
            }

        return f(*args, **kwargs)

    return decorated


def get_current_user() -> Optional[Dict]:
    """
    获取当前登录用户信息

    Returns:
        用户信息字典，未认证返回 None
    """
    return getattr(request, 'current_user', None)


# ==================== 兼容旧代码 ====================

# 别名
require_auth = require_gateway_auth


def get_user_permissions(role: str):
    """
    兼容旧代码 - 权限由后端管理，此函数仅返回默认值
    """
    return ['public', 'internal', 'confidential']


def check_collection_permission(role: str, department: str, collection_name: str, operation: str = "read") -> bool:
    """
    兼容旧代码 - 权限由后端管理，默认返回 True
    """
    return True


def get_accessible_collections(role: str, department: str, operation: str = "read", all_collections=None):
    """
    兼容旧代码 - 返回所有向量库
    """
    if all_collections:
        return all_collections
    return ['public_kb']


def can_create_collection(role: str) -> bool:
    """兼容旧代码 - 权限由后端管理"""
    return True


def can_delete_collection(role: str) -> bool:
    """兼容旧代码 - 权限由后端管理"""
    return True


def require_role(*roles):
    """
    兼容旧代码 - 权限由后端管理，此装饰器不再执行权限验证
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated
    return decorator


def require_collection_permission(operation: str):
    """
    兼容旧代码 - 权限由后端管理，此装饰器不再执行权限验证
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated
    return decorator


def get_auth_manager():
    """兼容旧代码"""
    return _FakeAuthManager()


class _FakeAuthManager:
    """兼容旧代码的假 AuthManager"""

    @staticmethod
    def get_user_permissions(role: str):
        return ['public', 'internal', 'confidential']

    @staticmethod
    def get_accessible_collections(role: str, department: str):
        return ['public_kb']


def is_admin() -> bool:
    """检查当前用户是否为管理员"""
    user = get_current_user()
    return user is not None and user.get('role') == 'admin'


def is_manager_or_above() -> bool:
    """检查当前用户是否为经理或以上级别"""
    user = get_current_user()
    return user is not None and user.get('role') in ('admin', 'manager')


def normalize_department_name(department: str) -> str:
    """兼容旧代码 - 部门名称标准化"""
    if not department:
        return ""
    if department.replace("_", "").replace("-", "").isalnum() and department.isascii():
        return department.lower()
    return ""
