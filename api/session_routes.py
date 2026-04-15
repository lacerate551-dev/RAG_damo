"""
会话管理 API

路由:
- GET    /sessions              - 用户会话列表
- GET    /history/<session_id>  - 获取会话历史
- DELETE /session/<session_id>  - 删除会话
- POST   /clear/<session_id>   - 清空会话历史
"""

from flask import Blueprint, request, jsonify, current_app
from auth.gateway import require_gateway_auth

session_bp = Blueprint('session', __name__)


@session_bp.route('/sessions', methods=['GET'])
@require_gateway_auth
def get_sessions():
    """
    获取用户的会话列表

    返回:
    {
        "sessions": [
            {
                "session_id": "...",
                "created_at": "...",
                "last_active": "...",
                "preview": "最后一条消息预览..."
            }
        ]
    }
    """
    session_manager = current_app.config['SESSION_MANAGER']
    user_id = request.current_user["user_id"]

    sessions = session_manager.get_user_sessions(user_id, limit=20)

    # 添加最后一条消息预览
    for s in sessions:
        history = session_manager.get_history(s["session_id"], limit=1)
        if history:
            s["preview"] = history[0]["content"][:50] + "..."
        else:
            s["preview"] = "空会话"

    return jsonify({"sessions": sessions})


@session_bp.route('/history/<session_id>', methods=['GET'])
@require_gateway_auth
def get_history(session_id):
    """
    获取会话历史

    返回:
    {
        "history": [
            {"role": "user/assistant", "content": "...", "created_at": "..."}
        ]
    }
    """
    session_manager = current_app.config['SESSION_MANAGER']
    user_id = request.current_user["user_id"]

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权访问此会话"}), 403

    history = session_manager.get_history(session_id, limit=100)

    return jsonify({"history": history})


@session_bp.route('/session/<session_id>', methods=['DELETE'])
@require_gateway_auth
def delete_session(session_id):
    """删除会话"""
    session_manager = current_app.config['SESSION_MANAGER']
    user_id = request.current_user["user_id"]

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权删除此会话"}), 403

    session_manager.delete_session(session_id)

    return jsonify({"success": True, "message": "会话已删除"})


@session_bp.route('/clear/<session_id>', methods=['POST'])
@require_gateway_auth
def clear_history(session_id):
    """清空会话历史（保留会话）"""
    session_manager = current_app.config['SESSION_MANAGER']
    user_id = request.current_user["user_id"]

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权操作此会话"}), 403

    session_manager.clear_history(session_id)

    return jsonify({"success": True, "message": "历史已清空"})
