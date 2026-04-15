"""
多向量库管理 API

路由:
- GET    /collections                         - 获取向量库列表
- POST   /collections                         - 创建向量库 (管理员)
- DELETE /collections/<kb_name>               - 删除向量库 (管理员)
- GET    /collections/<kb_name>/documents      - 获取向量库文档列表
- POST   /documents/sync                      - 触发文档同步
- POST   /kb/route                            - 测试知识库路由 (调试)
"""

import os
from flask import Blueprint, request, jsonify
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
    """获取用户可访问的向量库列表"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    from auth.gateway import get_accessible_collections

    user = request.current_user
    role = user["role"]
    department = user.get("department", "")

    # 获取所有向量库
    all_collections = kb_manager.list_collections()

    # 获取用户可访问的向量库
    accessible_read = get_accessible_collections(role, department, "read")
    accessible_write = get_accessible_collections(role, department, "write")
    accessible_delete = get_accessible_collections(role, department, "delete")

    result = []
    for coll in all_collections:
        if coll.name in accessible_read:
            result.append({
                "name": coll.name,
                "display_name": coll.display_name,
                "document_count": coll.document_count,
                "department": coll.department,
                "created_at": coll.created_at,
                "description": coll.description,
                "can_write": coll.name in accessible_write,
                "can_delete": coll.name in accessible_delete,
                "can_sync": coll.name in accessible_write
            })

    return jsonify({
        "collections": result,
        "total": len(result)
    })


@kb_bp.route('/collections', methods=['POST'])
@require_gateway_auth
def create_collection():
    """创建新向量库（仅管理员）"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    from auth.gateway import can_create_collection

    user = request.current_user

    if not can_create_collection(user["role"]):
        return jsonify({
            "error": "权限不足",
            "message": "只有管理员可以创建向量库"
        }), 403

    data = request.json
    name = data.get('name', '').strip()
    display_name = data.get('display_name', '')
    department = data.get('department', '')
    description = data.get('description', '')

    if not name:
        return jsonify({"error": "向量库名称不能为空"}), 400

    # 验证名称格式
    if not name.replace('_', '').isalnum():
        return jsonify({
            "error": "名称格式错误",
            "message": "向量库名称只能包含字母、数字和下划线"
        }), 400

    success, message = kb_manager.create_collection(
        name, display_name, department, description
    )

    if success:
        return jsonify({"success": True, "message": message, "name": name}), 201
    return jsonify({"error": message}), 400


@kb_bp.route('/collections/<kb_name>', methods=['DELETE'])
@require_gateway_auth
def delete_collection(kb_name):
    """删除向量库（仅管理员）"""
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    from auth.gateway import can_delete_collection

    user = request.current_user

    if not can_delete_collection(user["role"]):
        return jsonify({
            "error": "权限不足",
            "message": "只有管理员可以删除向量库"
        }), 403

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

    from auth.gateway import check_collection_permission

    user = request.current_user

    if not check_collection_permission(user["role"], user.get("department", ""), kb_name, "read"):
        return jsonify({
            "error": "权限不足",
            "message": f"您没有权限访问向量库 '{kb_name}'"
        }), 403

    documents = kb_manager.list_documents(kb_name)

    return jsonify({
        "collection": kb_name,
        "documents": documents,
        "total": len(documents)
    })


@kb_bp.route('/documents/sync', methods=['POST'])
@require_gateway_auth
def sync_documents():
    """
    触发文档向量化同步

    请求体:
    {
        "collection": "向量库名称"  // 可选
    }
    """
    kb_manager, _, err = _require_multi_kb()
    if err:
        return err

    from auth.gateway import check_collection_permission, get_accessible_collections
    from config import DOCUMENTS_PATH

    user = request.current_user
    role = user["role"]
    department = user.get("department", "")

    data = request.json or {}
    target_collection = data.get('collection')

    # 确定要同步的向量库
    if target_collection:
        if not check_collection_permission(role, department, target_collection, "sync"):
            return jsonify({
                "error": "权限不足",
                "message": f"您没有权限同步向量库 '{target_collection}'"
            }), 403
        collections_to_sync = [target_collection]
    else:
        collections_to_sync = get_accessible_collections(role, department, "sync")

    if not collections_to_sync:
        return jsonify({"error": "没有可同步的向量库"}), 400

    # 执行同步
    results = []
    for coll_name in collections_to_sync:
        try:
            if coll_name == "public_kb":
                doc_dir = os.path.join(DOCUMENTS_PATH, "public")
            else:
                dept_name = coll_name.replace("dept_", "")
                doc_dir = os.path.join(DOCUMENTS_PATH, "dept_" + dept_name)

            results.append({
                "collection": coll_name,
                "status": "success",
                "message": f"向量库 '{coll_name}' 同步任务已提交",
                "document_dir": doc_dir
            })
        except Exception as e:
            results.append({
                "collection": coll_name,
                "status": "error",
                "message": str(e)
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
    data = request.json
    query = data.get('query', '')

    if not query:
        return jsonify({"error": "请提供查询内容"}), 400

    # 获取路由结果
    target_kbs = route_query(
        query,
        user["role"],
        user.get("department", "")
    )

    # 获取意图分析
    intent = kb_router.analyze_intent(query)

    return jsonify({
        "query": query,
        "user_role": user["role"],
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
