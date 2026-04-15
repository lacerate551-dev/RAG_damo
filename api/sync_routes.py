"""
知识库同步 + 订阅通知 API

路由:
- POST   /sync              - 手动触发同步 (管理员)
- GET    /sync/status        - 获取同步状态
- GET    /sync/history       - 同步历史记录
- GET    /sync/changes       - 变更日志
- POST   /sync/start         - 启动文件监控 (管理员)
- POST   /sync/stop          - 停止文件监控 (管理员)
- POST   /subscribe          - 订阅文档变更
- DELETE /subscribe          - 取消订阅
- GET    /subscriptions      - 获取订阅列表
- GET    /notifications      - 获取通知
- POST   /notifications/<id>/read     - 标记已读
- POST   /notifications/read-all      - 全部已读
"""

from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth, require_role
from data.db import get_connection

sync_bp = Blueprint('sync', __name__)

# 延迟初始化同步服务
_sync_service = None
_sync_checked = False
_has_sync_service = False


def _get_sync_service():
    global _sync_service, _sync_checked, _has_sync_service
    if not _sync_checked:
        try:
            from knowledge.sync import KnowledgeSyncService
            from config import DOCUMENTS_PATH
            _sync_service = KnowledgeSyncService(documents_path=DOCUMENTS_PATH)
            _has_sync_service = True
        except (ImportError, Exception) as e:
            print(f"同步服务初始化失败: {e}")
            _has_sync_service = False
        _sync_checked = True
    return _sync_service


def _require_sync_service():
    """检查同步服务是否可用，返回 (service, error_response)"""
    service = _get_sync_service()
    if not _has_sync_service or not service:
        return None, (jsonify({"error": "同步服务未启用"}), 503)
    return service, None


# ==================== 同步 API ====================

@sync_bp.route('/sync', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def trigger_sync():
    """
    手动触发知识库同步

    请求体 (可选):
    {
        "full_sync": false  // 是否全量同步，默认false（增量同步）
    }
    """
    service, err = _require_sync_service()
    if err:
        return err

    data = request.json or {}
    full_sync = data.get('full_sync', False)

    try:
        result = service.sync_now()
        return jsonify(result.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sync_bp.route('/sync/status', methods=['GET'])
@require_gateway_auth
def get_sync_status():
    """获取同步状态"""
    service, err = _require_sync_service()
    if err:
        return jsonify({
            "enabled": False,
            "message": "同步服务未启用"
        })

    # 获取最近同步历史
    history = service.db.get_sync_history(limit=5)

    # 获取统计信息
    all_hashes = service.db.get_all_document_hashes()

    # 获取未处理的变更
    unprocessed_changes = service.db.get_change_logs(limit=100, processed=False)

    return jsonify({
        "enabled": True,
        "monitoring": service.is_running(),
        "documents_tracked": len(all_hashes),
        "unprocessed_changes": len(unprocessed_changes),
        "last_sync": history[0] if history else None,
        "recent_syncs": history
    })


@sync_bp.route('/sync/history', methods=['GET'])
@require_gateway_auth
def get_sync_history():
    """获取同步历史"""
    service, err = _require_sync_service()
    if err:
        return err

    limit = int(request.args.get('limit', 20))
    days = int(request.args.get('days', 30))

    history = service.db.get_sync_history(limit=limit)

    return jsonify({"history": history})


@sync_bp.route('/sync/changes', methods=['GET'])
@require_gateway_auth
def get_change_logs():
    """获取变更日志"""
    service, err = _require_sync_service()
    if err:
        return err

    limit = int(request.args.get('limit', 50))
    days = int(request.args.get('days', 30))
    processed = request.args.get('processed')

    if processed is not None:
        processed = processed.lower() == 'true'

    changes = service.db.get_change_logs(limit=limit, processed=processed, days=days)

    return jsonify({"changes": changes})


@sync_bp.route('/sync/start', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def start_sync_monitor():
    """启动文件监控"""
    service, err = _require_sync_service()
    if err:
        return err

    if service.is_running():
        return jsonify({"message": "文件监控已在运行"})

    success = service.start()
    if success:
        return jsonify({"message": "文件监控已启动"})
    else:
        return jsonify({"error": "启动文件监控失败"}), 500


@sync_bp.route('/sync/stop', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def stop_sync_monitor():
    """停止文件监控"""
    service, err = _require_sync_service()
    if err:
        return err

    service.stop()
    return jsonify({"message": "文件监控已停止"})


# ==================== 订阅与通知 API ====================

@sync_bp.route('/subscribe', methods=['POST'])
@require_gateway_auth
def subscribe_document():
    """
    订阅文档变更通知

    请求体:
    {
        "document_id": "xxx.pdf"  // 可选，不填则订阅所有文档
    }
    """
    service, err = _require_sync_service()
    if err:
        return err

    user_id = request.current_user["user_id"]
    data = request.json or {}
    document_id = data.get('document_id')
    document_name = data.get('document_name')

    service.db.subscribe(user_id, document_id, document_name)

    if document_id:
        message = f"已订阅文档: {document_id}"
    else:
        message = "已订阅所有文档变更通知"

    return jsonify({"success": True, "message": message})


@sync_bp.route('/subscribe', methods=['DELETE'])
@require_gateway_auth
def unsubscribe_document():
    """取消订阅"""
    service, err = _require_sync_service()
    if err:
        return err

    user_id = request.current_user["user_id"]
    data = request.json or {}
    document_id = data.get('document_id')

    service.db.unsubscribe(user_id, document_id)

    return jsonify({"success": True, "message": "已取消订阅"})


@sync_bp.route('/subscriptions', methods=['GET'])
@require_gateway_auth
def get_subscriptions():
    """获取当前用户的订阅列表"""
    service, err = _require_sync_service()
    if err:
        return err

    user_id = request.current_user["user_id"]

    with get_connection("knowledge") as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT document_id, document_name, created_at
            FROM subscriptions WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        rows = cursor.fetchall()

    subscriptions = [
        {
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "created_at": row["created_at"]
        }
        for row in rows
    ]

    return jsonify({"subscriptions": subscriptions})


@sync_bp.route('/notifications', methods=['GET'])
@require_gateway_auth
def get_notifications():
    """获取用户通知"""
    service, err = _require_sync_service()
    if err:
        return err

    user_id = request.current_user["user_id"]
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'

    notifications = service.db.get_notifications(user_id, unread_only)

    return jsonify({"notifications": notifications})


@sync_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@require_gateway_auth
def mark_notification_read(notification_id):
    """标记通知为已读"""
    service, err = _require_sync_service()
    if err:
        return err

    service.db.mark_notification_read(notification_id)

    return jsonify({"success": True, "message": "已标记为已读"})


@sync_bp.route('/notifications/read-all', methods=['POST'])
@require_gateway_auth
def mark_all_notifications_read():
    """标记所有通知为已读"""
    service, err = _require_sync_service()
    if err:
        return err

    user_id = request.current_user["user_id"]

    with get_connection("knowledge") as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE notifications SET read = 1 WHERE user_id = ?', (user_id,))

    return jsonify({"success": True, "message": "所有通知已标记为已读"})
