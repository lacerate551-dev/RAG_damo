"""
文档管理 + 版本管理 API

路由:
- POST   /documents/upload                                - 上传文件
- GET    /documents/list                                  - 文档列表
- DELETE /documents/<doc_path>                            - 删除文档
- POST   /documents/<collection>/<doc_path>/deprecate     - 废止文档
- POST   /documents/<collection>/<doc_path>/restore       - 恢复文档
- GET    /documents/<collection>/<doc_path>/versions       - 版本历史
- GET    /documents/<collection>/<doc_path>/info           - 文档状态
- GET    /documents/deprecated                            - 已废止文档列表
- POST   /search/version-aware                            - 版本感知检索
- POST   /documents/<collection>/<doc_path>/diff          - 版本差异对比
"""

import os
from datetime import datetime
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from auth.gateway import require_gateway_auth, check_collection_permission

document_bp = Blueprint('document', __name__)

# 文件限制
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# 延迟初始化版本管理模块
_version_checked = False
_has_version_management = False
_lifecycle_manager = None
_diff_analyzer = None


def _check_version_management():
    global _version_checked, _has_version_management, _lifecycle_manager, _diff_analyzer
    if not _version_checked:
        try:
            from knowledge.lifecycle import get_lifecycle_manager
            from knowledge.diff import get_diff_analyzer
            _lifecycle_manager = get_lifecycle_manager()
            _diff_analyzer = get_diff_analyzer()
            _has_version_management = True
        except ImportError as e:
            print(f"警告: 版本管理模块导入失败: {e}")
            _has_version_management = False
        _version_checked = True
    return _has_version_management


def _get_sync_service():
    """获取同步服务（可能不可用）"""
    try:
        from flask import current_app
        return current_app.config.get('SYNC_SERVICE')
    except Exception:
        return None


# ==================== 文档管理 ====================

@document_bp.route('/documents/upload', methods=['POST'])
@require_gateway_auth
def upload_document():
    """上传文件到知识库"""
    from config import DOCUMENTS_PATH
    from flask import current_app

    # 1. 检查文件
    if 'file' not in request.files:
        return jsonify({"error": "没有上传文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "没有选择文件"}), 400

    # 2. 获取目标向量库
    collection = request.form.get('collection') or request.form.get('kb_name')
    if not collection:
        return jsonify({"error": "请指定目标向量库 (collection 参数)"}), 400

    # 3. 权限验证
    user = request.current_user
    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'write'):
        return jsonify({
            "error": "权限不足",
            "message": f"您没有权限上传到此向量库",
            "your_role": user['role'],
            "your_department": user.get('department', ''),
            "target_collection": collection
        }), 403

    # 4. 文件类型验证
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"不支持的文件类型: {ext}，支持: pdf, docx, doc, xlsx, txt"}), 400

    # 5. 文件大小验证
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": f"文件大小超过限制 (最大 10MB)"}), 400

    # 6. 保存文件到对应目录
    if collection == 'public_kb':
        target_subdir = 'public'
    else:
        target_subdir = collection

    target_dir = os.path.join(DOCUMENTS_PATH, target_subdir)
    os.makedirs(target_dir, exist_ok=True)

    # 安全文件名 + 处理重名
    filename = secure_filename(file.filename)
    if not filename:
        filename = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"

    filepath = os.path.join(target_dir, filename)
    if os.path.exists(filepath):
        timestamp = datetime.now().strftime('_%Y%m%d_%H%M%S')
        name, ext_part = os.path.splitext(filename)
        filename = f"{name}{timestamp}{ext_part}"
        filepath = os.path.join(target_dir, filename)

    file.save(filepath)

    # 7. 触发向量化（如果有同步服务）
    sync_status = "已保存，等待手动同步"
    sync_service = _get_sync_service()
    if sync_service:
        try:
            from knowledge.sync import DocumentChange, ChangeType
            change = DocumentChange(
                document_id=f"{target_subdir}/{filename}",
                document_name=filename,
                change_type=ChangeType.ADDED,
                old_hash=None,
                new_hash=sync_service.calculate_file_hash(filepath),
                change_time=datetime.now()
            )
            sync_service.process_change(change)
            sync_status = "已保存并添加到向量库"
        except Exception as e:
            sync_status = f"已保存，向量化失败: {str(e)}"

    # 8. 审计日志
    audit_logger = current_app.config.get('AUDIT_LOGGER')
    if audit_logger:
        audit_logger.log(
            user_id=user['user_id'],
            action='upload_document',
            resource=filepath,
            details={"collection": collection, "size": file_size, "filename": filename}
        )

    return jsonify({
        "success": True,
        "message": f"文件上传成功，{sync_status}",
        "file": {
            "filename": filename,
            "collection": collection,
            "path": f"documents/{target_subdir}/{filename}",
            "size": file_size
        }
    })


@document_bp.route('/documents/list', methods=['GET'])
@require_gateway_auth
def list_documents():
    """获取文档列表"""
    from auth.gateway import get_accessible_collections
    from config import DOCUMENTS_PATH

    user = request.current_user
    accessible_collections = get_accessible_collections(user['role'], user.get('department', ''), 'read')

    # 可选过滤
    filter_collection = request.args.get('collection') or request.args.get('kb_name')
    if filter_collection and filter_collection not in accessible_collections:
        return jsonify({
            "error": "权限不足",
            "message": f"您没有权限查看此向量库",
            "target_collection": filter_collection
        }), 403

    collections_to_scan = [filter_collection] if filter_collection else accessible_collections

    documents = []
    supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}

    for coll in collections_to_scan:
        if coll == 'public_kb':
            subdir = 'public'
        else:
            subdir = coll

        level_dir = os.path.join(DOCUMENTS_PATH, subdir)
        if not os.path.exists(level_dir):
            continue

        for filename in os.listdir(level_dir):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in supported_extensions:
                continue

            filepath = os.path.join(level_dir, filename)
            try:
                stat = os.stat(filepath)
                documents.append({
                    "filename": filename,
                    "collection": coll,
                    "path": f"{subdir}/{filename}",
                    "size": stat.st_size,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except Exception as e:
                print(f"读取文件信息失败: {filename}, {e}")

    # 按修改时间倒序
    documents.sort(key=lambda x: x['last_modified'], reverse=True)

    return jsonify({
        "documents": documents,
        "total": len(documents)
    })


@document_bp.route('/documents/<path:doc_path>', methods=['DELETE'])
@require_gateway_auth
def delete_document(doc_path):
    """删除文档"""
    from config import DOCUMENTS_PATH
    from flask import current_app

    user = request.current_user

    # 解析路径
    parts = doc_path.split('/')
    if len(parts) < 2:
        return jsonify({"error": "无效的文档路径"}), 400

    subdir = parts[0]
    filename = '/'.join(parts[1:])

    # 将目录名转换为向量库名
    if subdir == 'public':
        collection = 'public_kb'
    else:
        collection = subdir

    # 权限验证
    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'delete'):
        return jsonify({
            "error": "权限不足",
            "message": f"您没有权限删除此向量库中的文档",
            "your_role": user['role'],
            "your_department": user.get('department', ''),
            "target_collection": collection
        }), 403

    # 文件路径
    filepath = os.path.join(DOCUMENTS_PATH, doc_path)
    if not os.path.exists(filepath):
        return jsonify({"error": "文件不存在"}), 404

    try:
        # 1. 从向量库删除
        sync_service = _get_sync_service()
        if sync_service:
            try:
                from knowledge.sync import DocumentChange, ChangeType
                change = DocumentChange(
                    document_id=doc_path,
                    document_name=filename,
                    change_type=ChangeType.DELETED,
                    old_hash=sync_service.calculate_file_hash(filepath) if os.path.exists(filepath) else None,
                    new_hash=None,
                    change_time=datetime.now()
                )
                sync_service.process_change(change)
            except Exception as e:
                print(f"从向量库删除失败: {e}")

        # 2. 删除文件
        os.remove(filepath)

        # 3. 审计日志
        audit_logger = current_app.config.get('AUDIT_LOGGER')
        if audit_logger:
            audit_logger.log(
                user_id=user['user_id'],
                action='delete_document',
                resource=filepath,
                details={"collection": collection, "filename": filename}
            )

        return jsonify({
            "success": True,
            "message": "文档已删除"
        })

    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500


# ==================== 版本管理 ====================

@document_bp.route('/documents/<collection>/<path:doc_path>/deprecate', methods=['POST'])
@require_gateway_auth
def deprecate_document_api(collection, doc_path):
    """废止文档（软删除）"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    from flask import current_app

    user = request.current_user

    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'delete'):
        return jsonify({
            "error": "权限不足",
            "message": f"您没有权限废止此向量库中的文档",
            "your_role": user['role'],
            "your_department": user.get('department', ''),
            "target_collection": collection
        }), 403

    data = request.json or {}
    reason = data.get('reason', '制度废止')

    result = _lifecycle_manager.deprecate_document(
        collection=collection,
        document_id=doc_path,
        reason=reason,
        deprecated_by=user.get('user_id', '')
    )

    # 审计日志
    audit_logger = current_app.config.get('AUDIT_LOGGER')
    if audit_logger:
        audit_logger.log(
            user_id=user['user_id'],
            action='deprecate_document',
            resource=f"{collection}/{doc_path}",
            details={"reason": reason, "affected_questions": len(result.get('affected_questions', []))}
        )

    return jsonify(result)


@document_bp.route('/documents/<collection>/<path:doc_path>/restore', methods=['POST'])
@require_gateway_auth
def restore_document_api(collection, doc_path):
    """恢复已废止的文档"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    user = request.current_user

    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'delete'):
        return jsonify({"error": "权限不足"}), 403

    result = _lifecycle_manager.restore_document(
        collection=collection,
        document_id=doc_path,
        restored_by=user.get('user_id', '')
    )

    return jsonify(result)


@document_bp.route('/documents/<collection>/<path:doc_path>/versions', methods=['GET'])
@require_gateway_auth
def get_document_versions_api(collection, doc_path):
    """获取文档版本历史"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    user = request.current_user
    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'read'):
        return jsonify({"error": "权限不足"}), 403

    limit = request.args.get('limit', 10, type=int)

    history = _lifecycle_manager.get_document_history(collection, doc_path, limit)

    return jsonify({
        "success": True,
        "document_id": doc_path,
        "collection": collection,
        "versions": [v.to_dict() for v in history],
        "total": len(history)
    })


@document_bp.route('/documents/<collection>/<path:doc_path>/info', methods=['GET'])
@require_gateway_auth
def get_document_info_api(collection, doc_path):
    """获取文档当前状态信息"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    user = request.current_user

    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'read'):
        return jsonify({"error": "权限不足"}), 403

    from knowledge.manager import get_kb_manager
    kb_manager = get_kb_manager()

    info = kb_manager.get_document_info(collection, doc_path)

    if not info:
        return jsonify({"error": "文档不存在"}), 404

    return jsonify({
        "success": True,
        "document": info
    })


@document_bp.route('/documents/deprecated', methods=['GET'])
@require_gateway_auth
def list_deprecated_documents_api():
    """列出已废止的文档"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    user = request.current_user
    collection = request.args.get('collection')
    limit = request.args.get('limit', 50, type=int)

    if collection:
        if not check_collection_permission(user['role'], user.get('department', ''), collection, 'read'):
            return jsonify({"error": "权限不足"}), 403

    deprecated_list = _lifecycle_manager.list_deprecated_documents(collection, limit)

    return jsonify({
        "success": True,
        "documents": [d.to_dict() for d in deprecated_list],
        "total": len(deprecated_list)
    })


@document_bp.route('/search/version-aware', methods=['POST'])
@require_gateway_auth
def version_aware_search_api():
    """版本感知检索"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    from knowledge.router import search_with_version_context

    user = request.current_user
    data = request.json or {}

    query = data.get('query', '')
    top_k = data.get('top_k', 5)
    include_deprecated = data.get('include_deprecated', False)

    if not query:
        return jsonify({"error": "缺少query参数"}), 400

    result = search_with_version_context(
        query=query,
        role=user['role'],
        department=user.get('department', ''),
        top_k=top_k
    )

    return jsonify({
        "success": True,
        "query": query,
        "results": result.get("results", []),
        "version_hints": result.get("version_hints", []),
        "target_collections": result.get("target_collections", [])
    })


@document_bp.route('/documents/<collection>/<path:doc_path>/diff', methods=['POST'])
@require_gateway_auth
def compare_document_versions_api(collection, doc_path):
    """对比文档版本差异"""
    if not _check_version_management():
        return jsonify({"error": "版本管理模块未启用"}), 503

    user = request.current_user

    if not check_collection_permission(user['role'], user.get('department', ''), collection, 'read'):
        return jsonify({"error": "权限不足"}), 403

    data = request.json or {}
    old_chunks = data.get('old_chunks')
    new_chunks = data.get('new_chunks')

    # 如果没有提供旧chunks，从向量库获取
    if old_chunks is None:
        from knowledge.manager import get_kb_manager
        kb_manager = get_kb_manager()
        old_chunks_data = kb_manager.get_document_chunks(collection, doc_path, status='active')

        if not old_chunks_data:
            return jsonify({"error": "未找到旧版本文档"}), 404

        old_chunks = [
            {
                "id": c["id"],
                "content": c["document"],
                "metadata": c["metadata"]
            }
            for c in old_chunks_data
        ]

    if not new_chunks:
        return jsonify({"error": "缺少new_chunks参数"}), 400

    # 计算差异
    diff_result = _diff_analyzer.compute_diff(old_chunks, new_chunks)

    return jsonify({
        "success": True,
        "document_id": doc_path,
        "collection": collection,
        "diff": diff_result.to_dict()
    })
