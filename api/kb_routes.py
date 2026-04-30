"""
多向量库管理 API

路由:
- GET    /collections                         - 获取向量库列表
- POST   /collections                         - 创建向量库
- PUT    /collections/<kb_name>               - 修改向量库
- DELETE /collections/<kb_name>               - 删除向量库
- GET    /collections/<kb_name>/documents     - 获取向量库文档列表
- GET    /collections/<kb_name>/chunks        - 获取向量库切片列表
- POST   /documents/sync                      - 触发文档同步
- POST   /kb/route                            - 测试知识库路由 (调试)

注意：权限验证由后端网关完成，RAG 服务不做权限判断
"""

import os
from flask import Blueprint, request, jsonify, current_app
from auth.gateway import require_gateway_auth

kb_bp = Blueprint('kb', __name__)

# 延迟初始化
_kb_manager = None
_kb_router = None
_kb_checked = False
_has_multi_kb = False


def _check_multi_kb():
    global _kb_checked, _has_multi_kb, _kb_manager, _kb_router
    if not _kb_checked:
        try:
            from knowledge.manager import get_kb_manager
            from knowledge.router import get_kb_router
            _kb_manager = get_kb_manager()
            _kb_router = get_kb_router()
            _has_multi_kb = True
        except ImportError as e:
            print(f"警告: 多向量库模块导入失败: {e}")
            _has_multi_kb = False
        _kb_checked = True
    return _has_multi_kb


def _require_multi_kb():
    """检查多向量库是否可用"""
    if not _check_multi_kb():
        return None, None, (jsonify({"error": "多向量库模块未启用"}), 503)
    return _kb_manager, _kb_router, None


@kb_bp.route('/collections', methods=['GET'])
@require_gateway_auth
def list_collections():
    """获取向量库列表"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    user = request.current_user

    # 获取所有向量库（权限由后端网关管理）
    all_collections = kb_manager.list_collections()

    result = []
    for coll in all_collections:
        result.append({
            "name": coll.name,
            "display_name": coll.display_name,
            "document_count": coll.document_count,
            "department": coll.department,
            "created_at": coll.created_at,
            "description": coll.description
        })

    return jsonify({
        "collections": result,
        "total": len(result)
    })


@kb_bp.route('/collections', methods=['POST'])
@require_gateway_auth
def create_collection():
    """创建新向量库"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    data = request.json or {}
    name = data.get('name', '').strip()
    display_name = data.get('display_name', '')
    department = data.get('department', '')
    description = data.get('description', '')

    if not name:
        return jsonify({"error": "向量库名称不能为空"}), 400

    # 验证名称格式（ChromaDB 限制）
    if not name.replace('_', '').replace('-', '').isalnum():
        return jsonify({
            "error": "名称格式错误",
            "message": "向量库名称只能包含字母、数字、下划线和连字符"
        }), 400

    success, message = kb_manager.create_collection(
        name, display_name, department, description
    )

    if success:
        return jsonify({"success": True, "message": message, "name": name}), 201
    return jsonify({"error": message}), 400


@kb_bp.route('/collections/<kb_name>', methods=['PUT'])
@require_gateway_auth
def update_collection(kb_name):
    """修改向量库信息"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    data = request.json or {}
    display_name = data.get('display_name')
    description = data.get('description')

    # 检查向量库是否存在
    collections = kb_manager.list_collections()
    if not any(c.name == kb_name for c in collections):
        return jsonify({"error": f"向量库 '{kb_name}' 不存在"}), 404

    # 更新元数据
    success = kb_manager.update_collection_metadata(
        kb_name,
        display_name=display_name,
        description=description
    )

    if success:
        return jsonify({"success": True, "message": "向量库信息已更新"})
    return jsonify({"error": "更新失败"}), 500


@kb_bp.route('/collections/<kb_name>', methods=['DELETE'])
@require_gateway_auth
def delete_collection(kb_name):
    """删除向量库"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    success, message = kb_manager.delete_collection(kb_name)

    if success:
        return jsonify({"success": True, "message": message})
    return jsonify({"error": message}), 400


@kb_bp.route('/collections/<kb_name>/documents', methods=['GET'])
@require_gateway_auth
def list_collection_documents(kb_name):
    """获取向量库中的文档列表"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    documents = kb_manager.list_documents(kb_name)

    return jsonify({
        "collection": kb_name,
        "documents": documents,
        "total": len(documents)
    })


@kb_bp.route('/collections/<kb_name>/chunks', methods=['GET'])
@require_gateway_auth
def list_collection_chunks(kb_name):
    """获取向量库中的切片列表"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    # 可选过滤参数
    document_id = request.args.get('document_id')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    chunks = kb_manager.list_chunks(kb_name, document_id=document_id, limit=limit, offset=offset)

    return jsonify({
        "collection": kb_name,
        "chunks": chunks,
        "total": len(chunks)
    })


@kb_bp.route('/documents/sync', methods=['POST'])
@require_gateway_auth
def sync_documents():
    """
    触发文档向量化同步

    请求体:
    {
        "collection": "向量库名称"  // 可选，不传则同步所有
    }
    """
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    from config import DOCUMENTS_PATH

    user = request.current_user
    data = request.json or {}
    target_collection = data.get('collection')

    # 确定要同步的向量库
    if target_collection:
        collections_to_sync = [target_collection]
    else:
        # 同步所有向量库
        all_collections = kb_manager.list_collections()
        collections_to_sync = [c.name for c in all_collections]

    if not collections_to_sync:
        return jsonify({"error": "没有可同步的向量库"}), 400

    # 执行同步
    results = []

    # 使用 sync_service 执行同步
    sync_service = current_app.config.get('SYNC_SERVICE')

    if sync_service:
        try:
            sync_result = sync_service.sync_now()
            results.append({
                "collection": "all",
                "status": "success",
                "message": f"同步完成: 处理 {sync_result.documents_processed} 个文档",
                "details": {
                    "added": sync_result.documents_added,
                    "modified": sync_result.documents_modified,
                    "deleted": sync_result.documents_deleted,
                    "errors": sync_result.errors
                }
            })
        except Exception as e:
            results.append({
                "collection": "all",
                "status": "error",
                "message": str(e)
            })
    else:
        # 没有 sync_service，返回提示
        for coll_name in collections_to_sync:
            results.append({
                "collection": coll_name,
                "status": "warning",
                "message": "同步服务不可用，请使用 POST /sync 端点"
            })

    return jsonify({
        "success": True,
        "results": results,
        "synced_count": len([r for r in results if r["status"] == "success"])
    })


@kb_bp.route('/kb/route', methods=['POST'])
@require_gateway_auth
def test_routing():
    """测试知识库路由（调试用）"""
    _, kb_router, err = _require_multi_kb()
    if err:
        return err

    from knowledge.router import route_query

    user = request.current_user
    data = request.json or {}
    query = data.get('query', '')

    if not query:
        return jsonify({"error": "请提供查询内容"}), 400

    # 获取路由结果
    target_kbs = route_query(
        query,
        user.get("role", "user"),
        user.get("department", "")
    )

    # 获取意图分析
    intent = kb_router.analyze_intent(query)

    return jsonify({
        "query": query,
        "user_role": user.get("role"),
        "user_department": user.get("department", ""),
        "target_collections": target_kbs,
        "intent": {
            "is_general": intent.is_general,
            "department": intent.department,
            "confidence": intent.confidence,
            "keywords": intent.keywords,
            "reason": intent.reason
        }
    })


# ==================== 文档版本管理 API ====================

@kb_bp.route('/collections/<kb_name>/documents/<path:filename>/deprecate', methods=['POST'])
@require_gateway_auth
def deprecate_document(kb_name, filename):
    """
    废止文档（软删除）

    请求体:
    {
        "reason": "废止原因"
    }

    返回:
    {
        "success": true,
        "deprecated_chunks": 15,
        "document_id": "报销制度.pdf",
        "collection": "public_kb",
        "deprecated_date": "2024-01-20T15:00:00"
    }
    """
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    user = request.current_user
    data = request.json or {}
    reason = data.get('reason', '文档已废止')

    try:
        result = kb_manager.deprecate_document(
            kb_name,
            filename,
            reason,
            deprecated_by=user.get('user_id', 'unknown')
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@kb_bp.route('/collections/<kb_name>/documents/<path:filename>/restore', methods=['POST'])
@require_gateway_auth
def restore_document(kb_name, filename):
    """
    恢复已废止的文档

    返回:
    {
        "success": true,
        "restored_chunks": 15,
        "document_id": "报销制度.pdf",
        "collection": "public_kb"
    }
    """
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    try:
        result = kb_manager.restore_document(kb_name, filename)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@kb_bp.route('/collections/<kb_name>/documents/<path:filename>/versions', methods=['GET'])
@require_gateway_auth
def get_document_versions(kb_name, filename):
    """
    获取文档版本历史

    查询参数:
    - limit: 返回数量限制（默认10）

    返回:
    {
        "success": true,
        "document_id": "报销制度.pdf",
        "collection": "public_kb",
        "versions": [
            {
                "version": "v2",
                "status": "active",
                "created_at": "2024-01-15T10:00:00",
                "chunk_count": 20
            },
            {
                "version": "v1",
                "status": "superseded",
                "created_at": "2023-01-01T10:00:00",
                "chunk_count": 15
            }
        ],
        "total": 2
    }
    """
    _, _, err = _require_multi_kb()
    if err:
        return err

    limit = request.args.get('limit', 10, type=int)

    try:
        from knowledge.document_versions import get_version_query
        version_query = get_version_query()

        versions = version_query.get_document_history(kb_name, filename, limit)
        versions_data = [v.to_dict() for v in versions]

        return jsonify({
            "success": True,
            "document_id": filename,
            "collection": kb_name,
            "versions": versions_data,
            "total": len(versions_data)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@kb_bp.route('/collections/<kb_name>/update-image-descriptions', methods=['POST'])
@require_gateway_auth
def update_image_descriptions(kb_name):
    """
    更新图片切片的轻量级描述（提取图号/表号）

    用于已入库的文档，重新生成图片描述以包含图号信息，提高检索准确度。

    返回:
    {
        "success": true,
        "image_count": 9,
        "updated_count": 5
    }
    """
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    try:
        result = kb_manager.update_image_descriptions(kb_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

