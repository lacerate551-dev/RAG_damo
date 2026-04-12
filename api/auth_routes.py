"""
认证与系统状态 API

路由:
- GET  /stats   - 系统统计 (管理员)
- GET  /health  - 健康检查
- GET  /auth/me - 当前用户信息
"""

from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth, require_role, get_user_permissions

auth_bp = Blueprint('auth', __name__)


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

    用户信息由网关注入到请求 Header 中：
    - X-User-ID: 用户唯一标识
    - X-User-Name: 用户名
    - X-User-Role: 用户角色
    - X-User-Department: 部门
    """
    user = request.current_user
    return jsonify({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "department": user["department"],
        "permissions": get_user_permissions(user["role"])
    })
