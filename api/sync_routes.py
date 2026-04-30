"""
知识库同步 API

路由:
- POST   /sync              - 手动触发同步
- GET    /sync/status       - 获取同步状态
- GET    /sync/history      - 同步历史记录
- GET    /sync/changes      - 变更日志
- POST   /sync/start        - 启动文件监控
- POST   /sync/stop         - 停止文件监控

注意：
- 订阅通知功能由后端负责
- 权限验证由后端网关完成
"""

from flask import Blueprint, request, jsonify, current_app
from auth.gateway import require_gateway_auth
from core.status_codes import SYNC_SUCCESS, SYNC_ERROR, INTERNAL_ERROR
from api.response_utils import success_response, error_response

sync_bp = Blueprint('sync', __name__)


def _get_sync_service():
    """获取同步服务实例"""
    try:
        return current_app.config.get('SYNC_SERVICE')
    except Exception:
        return None


def _require_sync_service():
    """检查同步服务是否可用"""
    service = _get_sync_service()
    if not service:
        return None, error_response(
            error="SERVICE_UNAVAILABLE",
            error_code=INTERNAL_ERROR,
            message="同步服务未启用",
            http_status=503
        )
    return service, None


# ==================== 同步 API ====================

@sync_bp.route('/sync', methods=['POST'])
@require_gateway_auth
def trigger_sync():
    """
    手动触发知识库同步

    请求体 (可选):
    {
        "collection": "向量库名称",  // 可选，不传则同步所有
        "full_sync": false          // 是否全量同步
    }
    """
    service, err = _require_sync_service()
    if err:
        return err

    try:
        result = service.sync_now()
        return success_response(
            data={"result": result.to_dict() if hasattr(result, 'to_dict') else result},
            status_code=SYNC_SUCCESS,
            message="同步完成"
        )
    except Exception as e:
        return error_response(
            error="SYNC_ERROR",
            error_code=SYNC_ERROR,
            message=str(e),
            http_status=500
        )


@sync_bp.route('/sync/status', methods=['GET'])
@require_gateway_auth
def get_sync_status():
    """获取同步状态"""
    service, err = _require_sync_service()
    if err:
        return jsonify({
            "status": "failed",
            "status_code": INTERNAL_ERROR,
            "enabled": False,
            "message": "同步服务未启用"
        })

    try:
        # 获取状态信息
        status = {
            "enabled": True,
            "monitoring": service.is_running() if hasattr(service, 'is_running') else False,
            "last_sync": None,
            "documents_tracked": 0
        }

        # 尝试获取更多状态信息
        if hasattr(service, 'get_status'):
            status.update(service.get_status())

        return jsonify(status)
    except Exception as e:
        return jsonify({
            "status": "failed",
            "status_code": INTERNAL_ERROR,
            "enabled": True,
            "error": str(e)
        })


@sync_bp.route('/sync/history', methods=['GET'])
@require_gateway_auth
def get_sync_history():
    """获取同步历史"""
    service, err = _require_sync_service()
    if err:
        return err

    limit = request.args.get('limit', 20, type=int)

    try:
        history = service.get_sync_history(limit=limit) if hasattr(service, 'get_sync_history') else []
        return jsonify({"history": history})
    except Exception as e:
        return error_response(
            error="SYNC_ERROR",
            error_code=SYNC_ERROR,
            message=str(e),
            http_status=500
        )


@sync_bp.route('/sync/changes', methods=['GET'])
@require_gateway_auth
def get_change_logs():
    """获取变更日志"""
    service, err = _require_sync_service()
    if err:
        return err

    limit = request.args.get('limit', 50, type=int)
    collection = request.args.get('collection')

    try:
        changes = service.get_change_logs(limit=limit, collection=collection) if hasattr(service, 'get_change_logs') else []
        return jsonify({"changes": changes})
    except Exception as e:
        return error_response(
            error="SYNC_ERROR",
            error_code=SYNC_ERROR,
            message=str(e),
            http_status=500
        )


@sync_bp.route('/sync/start', methods=['POST'])
@require_gateway_auth
def start_sync_monitor():
    """启动文件监控"""
    service, err = _require_sync_service()
    if err:
        return err

    try:
        if hasattr(service, 'is_running') and service.is_running():
            return jsonify({"status": "success", "status_code": SYNC_SUCCESS, "message": "文件监控已在运行"})

        if hasattr(service, 'start'):
            success = service.start()
            if success:
                return jsonify({"status": "success", "status_code": SYNC_SUCCESS, "message": "文件监控已启动"})
            else:
                return error_response(
                    error="SYNC_ERROR",
                    error_code=SYNC_ERROR,
                    message="启动文件监控失败",
                    http_status=500
                )
        else:
            return jsonify({"status": "success", "message": "文件监控功能不可用"})
    except Exception as e:
        return error_response(
            error="SYNC_ERROR",
            error_code=SYNC_ERROR,
            message=str(e),
            http_status=500
        )


@sync_bp.route('/sync/stop', methods=['POST'])
@require_gateway_auth
def stop_sync_monitor():
    """停止文件监控"""
    service, err = _require_sync_service()
    if err:
        return err

    try:
        if hasattr(service, 'stop'):
            service.stop()
        return jsonify({"status": "success", "status_code": SYNC_SUCCESS, "message": "文件监控已停止"})
    except Exception as e:
        return error_response(
            error="SYNC_ERROR",
            error_code=SYNC_ERROR,
            message=str(e),
            http_status=500
        )
