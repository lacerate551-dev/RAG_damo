"""
文档管理 API

路由:
- POST   /documents/upload              - 上传文件（单个）
- POST   /documents/batch-upload        - 批量上传文件
- GET    /documents/list                - 文档列表
- GET    /documents/<doc_id>/status     - 文件处理状态
- PUT    /documents/<doc_id>            - 更新文件
- DELETE /documents/<doc_path>          - 删除文档
- GET    /documents/<doc_id>/chunks     - 查看文件切片

切片管理:
- POST   /chunks                        - 新增切片
- PUT    /chunks/<chunk_id>             - 修改切片
- DELETE /chunks/<chunk_id>             - 删除切片

注意：权限验证由后端网关完成，RAG 服务不做权限判断
"""

import os
import re
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from auth.gateway import require_gateway_auth

document_bp = Blueprint('document', __name__)

# 文件限制
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def safe_filename(filename: str) -> str:
    """
    安全文件名处理 - 保留中文，仅移除危险字符

    与 secure_filename() 不同，此函数保留 Unicode 字符（包括中文），
    仅移除路径分隔符和其他危险字符。

    Args:
        filename: 原始文件名

    Returns:
        安全的文件名
    """
    if not filename:
        return ""

    # 移除路径分隔符和危险字符
    dangerous_chars = ['/', '\\', '..', '\x00', '\n', '\r', '\t']
    safe_name = filename
    for char in dangerous_chars:
        safe_name = safe_name.replace(char, '_')

    # 移除首尾空格和点
    safe_name = safe_name.strip(' .')

    # 如果文件名为空或只有扩展名，返回空
    if not safe_name or safe_name.startswith('.') and safe_name.count('.') == 1:
        return ""

    return safe_name

# 延迟初始化
_kb_manager = None
_kb_checked = False


def _get_kb_manager():
    """获取知识库管理器"""
    global _kb_manager, _kb_checked
    if not _kb_checked:
        try:
            from knowledge.manager import get_kb_manager
            _kb_manager = get_kb_manager()
        except ImportError as e:
            print(f"警告: 知识库管理器导入失败: {e}")
        _kb_checked = True
    return _kb_manager


def _get_sync_service():
    """获取同步服务"""
    try:
        from flask import current_app
        return current_app.config.get('SYNC_SERVICE')
    except Exception:
        return None


# ==================== 文档管理 ====================

@document_bp.route('/documents/upload', methods=['POST'])
@require_gateway_auth
def upload_document():
    """
    上传单个文件到知识库

    表单参数:
    - file: 文件（必需）
    - collection: 目标向量库名称（必需）

    返回:
    - success: 是否成功
    - file: 文件信息
    """
    from config import DOCUMENTS_PATH

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

    # 3. 文件类型验证
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"不支持的文件类型: {ext}，支持: pdf, docx, doc, xlsx, txt"}), 400

    # 4. 文件大小验证
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": f"文件大小超过限制 (最大 10MB)"}), 400

    # 5. 保存文件到对应目录
    if collection == 'public_kb':
        target_subdir = 'public'
    else:
        target_subdir = collection

    target_dir = os.path.join(DOCUMENTS_PATH, target_subdir)
    os.makedirs(target_dir, exist_ok=True)

    # 安全文件名 + 处理重名
    original_filename = file.filename
    ext = os.path.splitext(original_filename)[1].lower()
    filename = safe_filename(original_filename)
    if not filename:
        filename = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"

    filepath = os.path.join(target_dir, filename)
    if os.path.exists(filepath):
        timestamp = datetime.now().strftime('_%Y%m%d_%H%M%S')
        name, ext_part = os.path.splitext(filename)
        filename = f"{name}{timestamp}{ext_part}"
        filepath = os.path.join(target_dir, filename)

    file.save(filepath)

    # 6. 触发向量化
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

    return jsonify({
        "success": True,
        "message": f"文件上传成功，{sync_status}",
        "file": {
            "filename": filename,
            "collection": collection,
            "path": f"{target_subdir}/{filename}",
            "size": file_size
        }
    })


@document_bp.route('/documents/batch-upload', methods=['POST'])
@require_gateway_auth
def batch_upload_documents():
    """
    批量上传文件到知识库

    表单参数:
    - files: 文件列表（必需）
    - collection: 目标向量库名称（必需）

    返回:
    - success: 是否成功
    - results: 每个文件的上传结果
    """
    from config import DOCUMENTS_PATH

    # 检查文件
    if 'files' not in request.files:
        return jsonify({"error": "没有上传文件"}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({"error": "没有选择文件"}), 400

    # 获取目标向量库
    collection = request.form.get('collection') or request.form.get('kb_name')
    if not collection:
        return jsonify({"error": "请指定目标向量库 (collection 参数)"}), 400

    # 确定存储目录
    if collection == 'public_kb':
        target_subdir = 'public'
    else:
        target_subdir = collection

    target_dir = os.path.join(DOCUMENTS_PATH, target_subdir)
    os.makedirs(target_dir, exist_ok=True)

    # 批量处理
    results = []
    for file in files:
        if file.filename == '':
            continue

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": f"不支持的文件类型: {ext}"
            })
            continue

        try:
            original_filename = file.filename
            ext = os.path.splitext(original_filename)[1].lower()
            filename = safe_filename(original_filename)
            if not filename:
                filename = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
            filepath = os.path.join(target_dir, filename)

            # 处理重名
            if os.path.exists(filepath):
                timestamp = datetime.now().strftime('_%Y%m%d_%H%M%S')
                name, ext_part = os.path.splitext(filename)
                filename = f"{name}{timestamp}{ext_part}"
                filepath = os.path.join(target_dir, filename)

            file.save(filepath)

            results.append({
                "filename": filename,
                "status": "success",
                "path": f"{target_subdir}/{filename}"
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": str(e)
            })

    # 触发同步
    sync_service = _get_sync_service()
    if sync_service:
        try:
            sync_service.sync_directory(target_dir, collection)
        except Exception as e:
            print(f"批量同步失败: {e}")

    return jsonify({
        "success": True,
        "total": len(results),
        "success_count": len([r for r in results if r["status"] == "success"]),
        "results": results
    })


@document_bp.route('/documents/list', methods=['GET'])
@require_gateway_auth
def list_documents():
    """
    获取文档列表

    查询参数:
    - collection: 过滤向量库（可选）
    """
    from config import DOCUMENTS_PATH

    collection = request.args.get('collection') or request.args.get('kb_name')

    # 确定要扫描的目录
    if collection:
        if collection == 'public_kb':
            subdirs = ['public']
        else:
            subdirs = [collection]
    else:
        # 列出所有文档目录
        subdirs = []
        if os.path.exists(DOCUMENTS_PATH):
            for d in os.listdir(DOCUMENTS_PATH):
                if os.path.isdir(os.path.join(DOCUMENTS_PATH, d)):
                    subdirs.append(d)

    documents = []
    supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}

    for subdir in subdirs:
        level_dir = os.path.join(DOCUMENTS_PATH, subdir)
        if not os.path.exists(level_dir):
            continue

        # 确定向量库名
        if subdir == 'public':
            coll_name = 'public_kb'
        else:
            coll_name = subdir

        for filename in os.listdir(level_dir):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in supported_extensions:
                continue

            filepath = os.path.join(level_dir, filename)
            try:
                stat = os.stat(filepath)
                documents.append({
                    "filename": filename,
                    "collection": coll_name,
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


@document_bp.route('/documents/<path:doc_path>/status', methods=['GET'])
@require_gateway_auth
def get_document_status(doc_path):
    """获取文件处理状态"""
    kb_manager = _get_kb_manager()
    if not kb_manager:
        return jsonify({"error": "知识库管理器未初始化"}), 503

    # 解析路径
    parts = doc_path.split('/')
    if len(parts) < 2:
        return jsonify({"error": "无效的文档路径"}), 400

    subdir = parts[0]
    filename = '/'.join(parts[1:])

    # 确定向量库
    if subdir == 'public':
        collection = 'public_kb'
    else:
        collection = subdir

    # 获取文档信息
    doc_info = kb_manager.get_document_info(collection, doc_path)

    if not doc_info:
        return jsonify({"error": "文档不存在"}), 404

    return jsonify({
        "success": True,
        "status": doc_info.get("status", "unknown"),
        "chunk_count": doc_info.get("chunk_count", 0),
        "last_processed": doc_info.get("last_processed")
    })


@document_bp.route('/documents/<path:doc_path>', methods=['PUT'])
@require_gateway_auth
def update_document(doc_path):
    """更新文件（重新上传覆盖）"""
    from config import DOCUMENTS_PATH

    if 'file' not in request.files:
        return jsonify({"error": "没有上传文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "没有选择文件"}), 400

    # 解析路径
    parts = doc_path.split('/')
    if len(parts) < 2:
        return jsonify({"error": "无效的文档路径"}), 400

    filepath = os.path.join(DOCUMENTS_PATH, doc_path)
    if not os.path.exists(filepath):
        return jsonify({"error": "文件不存在"}), 404

    # 覆盖文件
    file.save(filepath)

    # 触发重新向量化
    sync_service = _get_sync_service()
    if sync_service:
        try:
            subdir = parts[0]
            filename = '/'.join(parts[1:])
            from knowledge.sync import DocumentChange, ChangeType
            change = DocumentChange(
                document_id=doc_path,
                document_name=filename,
                change_type=ChangeType.MODIFIED,
                old_hash=None,
                new_hash=sync_service.calculate_file_hash(filepath),
                change_time=datetime.now()
            )
            sync_service.process_change(change)
        except Exception as e:
            print(f"重新向量化失败: {e}")

    return jsonify({
        "success": True,
        "message": "文件已更新"
    })


@document_bp.route('/documents/<path:doc_path>', methods=['DELETE'])
@require_gateway_auth
def delete_document(doc_path):
    """删除文档"""
    from config import DOCUMENTS_PATH

    # 解析路径
    parts = doc_path.split('/')
    if len(parts) < 2:
        return jsonify({"error": "无效的文档路径"}), 400

    subdir = parts[0]
    filename = '/'.join(parts[1:])

    # 确定向量库
    if subdir == 'public':
        collection = 'public_kb'
    else:
        collection = subdir

    filepath = os.path.join(DOCUMENTS_PATH, doc_path)
    if not os.path.exists(filepath):
        return jsonify({"error": "文件不存在"}), 404

    try:
        # 1. 从向量库删除
        kb_manager = _get_kb_manager()
        if kb_manager:
            kb_manager.delete_document(collection, doc_path)

        # 2. 删除文件
        os.remove(filepath)

        return jsonify({
            "success": True,
            "message": "文档已删除"
        })

    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500


@document_bp.route('/documents/<path:doc_path>/chunks', methods=['GET'])
@require_gateway_auth
def list_document_chunks(doc_path):
    """查看文件切片"""
    kb_manager = _get_kb_manager()
    if not kb_manager:
        return jsonify({"error": "知识库管理器未初始化"}), 503

    # 解析路径
    parts = doc_path.split('/')
    if len(parts) < 2:
        return jsonify({"error": "无效的文档路径"}), 400

    subdir = parts[0]
    if subdir == 'public':
        collection = 'public_kb'
    else:
        collection = subdir

    chunks = kb_manager.get_document_chunks(collection, os.path.basename(doc_path))

    return jsonify({
        "success": True,
        "document_id": doc_path,
        "collection": collection,
        "chunks": chunks,
        "total": len(chunks)
    })


# ==================== 切片管理 ====================

@document_bp.route('/chunks', methods=['POST'])
@require_gateway_auth
def create_chunk():
    """
    新增切片

    请求体:
    {
        "collection": "向量库名称",
        "content": "切片内容",
        "metadata": {} // 可选
    }
    """
    kb_manager = _get_kb_manager()
    if not kb_manager:
        return jsonify({"error": "知识库管理器未初始化"}), 503

    data = request.json or {}
    collection = data.get('collection')
    content = data.get('content')
    metadata = data.get('metadata', {})

    if not collection:
        return jsonify({"error": "请指定向量库 (collection)"}), 400
    if not content:
        return jsonify({"error": "切片内容不能为空"}), 400

    chunk_id = kb_manager.add_chunk(collection, content, metadata)

    return jsonify({
        "success": True,
        "chunk_id": chunk_id,
        "message": "切片已添加"
    })


@document_bp.route('/chunks/<chunk_id>', methods=['PUT'])
@require_gateway_auth
def update_chunk(chunk_id):
    """
    修改切片

    请求体:
    {
        "collection": "向量库名称",
        "content": "新内容",  // 可选
        "metadata": {}  // 可选
    }
    """
    kb_manager = _get_kb_manager()
    if not kb_manager:
        return jsonify({"error": "知识库管理器未初始化"}), 503

    data = request.json or {}
    collection = data.get('collection')
    content = data.get('content')
    metadata = data.get('metadata')

    if not collection:
        return jsonify({"error": "请指定向量库 (collection)"}), 400

    success = kb_manager.update_chunk(collection, chunk_id, content=content, metadata=metadata)

    if success:
        return jsonify({"success": True, "message": "切片已更新"})
    return jsonify({"error": "更新失败"}), 500


@document_bp.route('/chunks/<chunk_id>', methods=['DELETE'])
@require_gateway_auth
def delete_chunk(chunk_id):
    """删除切片"""
    data = request.json or {}
    collection = data.get('collection')

    if not collection:
        collection = request.args.get('collection')

    if not collection:
        return jsonify({"error": "请指定向量库 (collection)"}), 400

    kb_manager = _get_kb_manager()
    if not kb_manager:
        return jsonify({"error": "知识库管理器未初始化"}), 503

    success = kb_manager.delete_chunk(collection, chunk_id)

    if success:
        return jsonify({"success": True, "message": "切片已删除"})
    return jsonify({"error": "删除失败"}), 500
