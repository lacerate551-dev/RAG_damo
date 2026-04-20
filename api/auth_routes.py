"""
认证与系统状态 API

路由:
- POST /auth/login - 模拟登录（仅开发环境）
- GET  /stats      - 系统统计 (管理员)
- GET  /health     - 健康检查
- GET  /auth/me    - 当前用户信息
"""

from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth, require_role, get_user_permissions, MOCK_USERS
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录）
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/auth/login', methods=['POST'])
def mock_login():
    """
    模拟登录（仅开发环境）

    请求体:
    {
        "username": "admin",
        "password": "admin123"
    }

    返回:
    {
        "token": "mock-token-admin",
        "user": {
            "user_id": "admin001",
            "username": "admin",
            "role": "admin",
            "department": "管理部"
        }
    }

    测试账号:
    - admin / admin123 (管理员，可访问所有文档)
    - testuser / test123 (普通用户，仅访问 public + internal)
    - manager / manager123 (经理，可访问 confidential)
    """
    # 默认开启开发模式（生产环境需设置 DEV_MODE=false）
    if os.environ.get('DEV_MODE', 'true').lower() == 'false':
        return jsonify({"error": "仅开发环境可用，请设置 DEV_MODE=true"}), 403

    data = request.json or {}
    username = data.get('username')
    password = data.get('password')

    user = MOCK_USERS.get(username)
    if not user or user['password'] != password:
        return jsonify({"error": "用户名或密码错误"}), 401

    return jsonify({
        "token": f"mock-token-{username}",
        "user": {
            "user_id": user['user_id'],
            "username": username,
            "role": user['role'],
            "department": user['department']
        }
    })


@auth_bp.route('/stats', methods=['GET'])
@require_gateway_auth
@require_role('admin')
def get_stats():
    """获取系统统计信息（仅管理员）"""
    from flask import current_app
    session_manager = current_app.config['SESSION_MANAGER']
    return jsonify(session_manager.get_stats())


@auth_bp.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "knowledge_base": "多向量库模式 (按集合提供服务)",
        "bm25_index": "动态按需加载",
        "mode": "Agentic RAG"
    })


@auth_bp.route('/auth/me', methods=['GET'])
@require_gateway_auth
def get_current_user():
    """
    获取当前用户信息

    开发模式下支持模拟用户，生产模式下用户信息由后端控制。
    """
    user = request.current_user
    return jsonify({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "department": user["department"],
        "permissions": get_user_permissions(user["role"])
    })
