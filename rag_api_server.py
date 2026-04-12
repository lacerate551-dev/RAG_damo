"""
带会话管理的 RAG API 服务 - 使用 Agentic RAG

提供 REST API 接口供前端和 Dify 工作流调用：
1. POST /chat - 发送消息并获取回复（普通聊天，直接LLM回复）
2. POST /rag - 发送消息并获取回复（知识库问答，使用Agentic RAG）
3. POST /search - 混合检索接口（供 Dify 工作流调用）
4. GET /sessions - 获取用户会话列表
5. DELETE /session/<session_id> - 删除会话
6. GET /history/<session_id> - 获取会话历史
7. 出题系统 API - 生成试卷、审核、批卷

特性：
- 双模式：普通聊天 / 知识库问答
- 多轮对话：记住上下文
- 用户隔离：不同用户会话独立
- 并发支持：多用户同时请求
- Dify 集成：提供 HTTP 检索接口
- 出题系统：智能出题、审核、批卷

使用方式：
    python rag_api_server.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os
import pickle
import numpy as np
import sqlite3
from dataclasses import asdict
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.session import SessionManager
from auth.gateway import require_gateway_auth, require_role, get_user_permissions, get_auth_manager
from services.audit import AuditLogger
from auth.security import validate_query, sanitize_user_input, filter_response, AgentConstraints
from core.agentic import AgenticRAG
from rag_demo import (
    collection, API_KEY, BASE_URL, MODEL,
    embedding_model, reranker, EMBEDDING_MODEL_PATH, RERANK_MODEL_PATH,
    CHROMA_DB_PATH, VECTOR_WEIGHT, BM25_WEIGHT, DOCUMENTS_PATH
)
from openai import OpenAI
from rank_bm25 import BM25Okapi
import jieba

# 导入出题系统 API 蓝图
try:
    from exam_pkg.api import exam_bp
    HAS_EXAM_API = True
except ImportError as e:
    print(f"警告: 出题系统模块导入失败: {e}")
    HAS_EXAM_API = False

# 初始化
app = Flask(__name__)
CORS(app)

# 注册出题系统蓝图
if HAS_EXAM_API:
    app.register_blueprint(exam_bp, url_prefix='/exam')
    print("出题系统 API 已启用: /exam")

# 会话管理器
session_manager = SessionManager(db_path="./data/sessions.db", session_expire_hours=24)

# 认证管理器（兼容旧代码，实际使用网关认证）
auth_manager = get_auth_manager()

# 审计日志
audit_logger = AuditLogger(db_path="./data/sessions.db")

# Agentic RAG 实例（用于知识库问答）
agentic_rag = AgenticRAG()

# LLM 客户端（用于普通聊天，使用更快的模型）
llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
CHAT_MODEL = "qwen3.5-flash"  # 聊天使用更快的模型

# 混合检索模式下，不再统一加载单个 BM25 索引，改为按需加载 (KnowledgeBaseManager实现)
bm25 = None
bm25_docs = []



def chat_with_llm(message: str, history: list = None, enable_web_search: bool = True) -> dict:
    """
    智能聊天 - 使用 Agentic RAG 的网络搜索能力

    Args:
        message: 用户消息
        history: 对话历史
        enable_web_search: 是否启用网络搜索

    Returns:
        {"answer": 回答内容, "sources": 来源列表, "web_searched": 是否进行了网络搜索}
    """
    # 使用 Agentic RAG 处理，启用网络搜索但不使用知识库
    result = agentic_rag.chat_search(
        message,
        history=history,
        enable_web_search=enable_web_search,
        verbose=False
    )
    return result


# ============== 混合检索功能（供 Dify 调用）==============

def reciprocal_rank_fusion(results_list, weights=None, k=60):
    """RRF 融合算法"""
    if weights is None:
        weights = [1.0] * len(results_list)

    doc_scores = {}
    for results, weight in zip(results_list, weights):
        if not results['documents'][0]:
            continue
        for rank, (doc_id, doc, meta) in enumerate(zip(
            results['ids'][0],
            results['documents'][0],
            results['metadatas'][0]
        )):
            rrf_score = weight / (k + rank + 1)
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {'score': 0.0, 'doc': doc, 'meta': meta}
            doc_scores[doc_id]['score'] += rrf_score

    sorted_items = sorted(doc_scores.items(), key=lambda x: x[1]['score'], reverse=True)
    return {
        'ids': [[item[0] for item in sorted_items]],
        'documents': [[item[1]['doc'] for item in sorted_items]],
        'metadatas': [[item[1]['meta'] for item in sorted_items]],
        'distances': [[item[1]['score'] for item in sorted_items]]
    }


def search_hybrid(query: str, top_k: int = 5, candidates: int = 15, allowed_levels: list = None, allowed_collections: list = None) -> dict:
    """混合检索 + Rerank，支持多向量库模式"""
    # 尝试使用最新的多数据库管理器
    try:
        from knowledge.manager import get_kb_manager
        kb_manager = get_kb_manager()
        
        target_kbs = allowed_collections if allowed_collections else ["public_kb"]
        query_vector = embedding_model.encode(query).tolist()
        
        # 内部已经包含了 RRF 和 BM25 的检索逻辑
        multi_result = kb_manager.search_multiple(
            kb_names=target_kbs,
            query_vector=query_vector,
            query_text=query,
            top_k=candidates,
            use_bm25=True
        )
        
        fused_docs = multi_result.documents
        fused_ids = multi_result.ids
        fused_metas = multi_result.metadatas
        fused_distances = multi_result.distances
        
    except ImportError:
        # 降级处理：原始单库模式 (向量检索)
        query_vector = embedding_model.encode(query).tolist()
        query_kwargs = {"query_embeddings": [query_vector], "n_results": candidates}
        if allowed_levels:
            query_kwargs["where"] = {"security_level": {"$in": allowed_levels}}
        vector_results = collection.query(**query_kwargs)
        
        if not vector_results['documents'] or not vector_results['documents'][0]:
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}
            
        fused_docs = vector_results['documents'][0]
        fused_ids = vector_results['ids'][0]
        fused_metas = vector_results['metadatas'][0]
        fused_distances = vector_results['distances'][0]

    # Rerank
    if reranker and len(fused_docs) > 0:
        pairs = [(query, doc) for doc in fused_docs]
        scores = reranker.predict(pairs)
        sorted_indices = np.argsort(scores)[::-1][:top_k]
        return {
            'ids': [[fused_ids[i] for i in sorted_indices]],
            'documents': [[fused_docs[i] for i in sorted_indices]],
            'metadatas': [[fused_metas[i] for i in sorted_indices]],
            'distances': [[float(scores[i]) for i in sorted_indices]]
        }

    return {
        'ids': [fused_ids[:top_k]],
        'documents': [fused_docs[:top_k]],
        'metadatas': [fused_metas[:top_k]],
        'distances': [fused_distances[:top_k]]
    }


@app.route('/chat', methods=['POST'])
@require_gateway_auth
def chat():
    """
    普通聊天模式 - 直接使用LLM回复，速度快

    请求体:
    {
        "session_id": "会话ID（首次为null）",
        "message": "消息内容"
    }

    返回:
    {
        "session_id": "会话ID",
        "answer": "回复内容",
        "mode": "chat"
    }
    """
    data = request.json

    user_id = request.current_user["user_id"]
    session_id = data.get('session_id')
    message = data.get('message')

    if not message:
        return jsonify({"error": "缺少 message"}), 400

    # 输入安全验证
    is_valid, reason = validate_query(message)
    if not is_valid:
        return jsonify({"error": reason}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 智能聊天（支持网络搜索）
    result = chat_with_llm(message, history)

    # 保存助手回复（过滤敏感信息）
    answer = filter_response(result["answer"])
    session_manager.add_message(session_id, "assistant", answer)

    return jsonify({
        "session_id": session_id,
        "answer": answer,
        "mode": "chat",
        "sources": result.get("sources", []),
        "web_searched": result.get("web_searched", False)
    })


@app.route('/rag/stream', methods=['POST'])
@require_gateway_auth
def rag_stream():
    """
    知识库问答模式 - SSE 流式返回（包含思考过程日志）

    请求体:
    {
        "session_id": "会话ID（首次为null）",
        "message": "消息内容"
    }

    返回: SSE 流，每个事件格式:
    data: {"type": "decision/retrieve/answer/complete", ...}
    """
    from flask import Response
    import json
    import queue
    import threading

    data = request.json
    user_id = request.current_user["user_id"]
    session_id = data.get('session_id')
    message = data.get('message')

    if not message:
        return jsonify({"error": "缺少 message"}), 400

    # 输入安全验证
    is_valid, reason = validate_query(message)
    if not is_valid:
        return jsonify({"error": reason}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 获取用户权限
    allowed_levels = auth_manager.get_user_permissions(request.current_user["role"])

    # 创建消息队列用于 SSE
    log_queue = queue.Queue()

    def log_callback(event):
        """日志回调，将事件放入队列"""
        log_queue.put(event)

    def generate():
        """生成 SSE 流"""
        try:
            # 在后台线程中处理
            result_holder = {'result': None}

            def process():
                result = agentic_rag.process(
                    message,
                    verbose=False,
                    history=history,
                    log_callback=log_callback,
                    allowed_levels=allowed_levels,
                    role=request.current_user["role"],
                    department=request.current_user.get("department", "")
                )
                result_holder['result'] = result

            thread = threading.Thread(target=process)
            thread.start()

            # 实时发送日志事件
            while thread.is_alive() or not log_queue.empty():
                try:
                    event = log_queue.get(timeout=0.1)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    continue

            thread.join()
            result = result_holder['result']

            # 保存助手回复
            if result:
                session_manager.add_message(session_id, "assistant", result["answer"])

                # 发送最终结果
                final_event = {
                    "type": "result",
                    "session_id": session_id,
                    "answer": result["answer"],
                    "mode": "rag",
                    "sources": result.get("sources", []),
                    "log_trace": result.get("log_trace", [])
                }
                yield f"data: {json.dumps(final_event, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/rag', methods=['POST'])
@require_gateway_auth
def rag():
    """
    知识库问答模式 - 使用Agentic RAG检索回复

    请求体:
    {
        "session_id": "会话ID（首次为null）",
        "message": "消息内容"
    }

    返回:
    {
        "session_id": "会话ID",
        "answer": "回复内容",
        "mode": "rag",
        "sources": [{"source": "文件名", "snippet": "..."}]
    }
    """
    data = request.json

    user_id = request.current_user["user_id"]
    session_id = data.get('session_id')
    message = data.get('message')

    if not message:
        return jsonify({"error": "缺少 message"}), 400

    # 输入安全验证
    is_valid, reason = validate_query(message)
    if not is_valid:
        return jsonify({"error": reason}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 获取用户权限
    allowed_levels = auth_manager.get_user_permissions(request.current_user["role"])

    # 使用 Agentic RAG 处理
    import time as _time
    _start = _time.time()
    result = agentic_rag.process(message, verbose=False, history=history,
                                 allowed_levels=allowed_levels,
                                 role=request.current_user["role"],
                                 department=request.current_user.get("department", ""))
    _duration = int((_time.time() - _start) * 1000)

    # 保存助手回复
    session_manager.add_message(session_id, "assistant", result["answer"])

    # 记录审计日志
    audit_logger.log_query(
        user_id=user_id,
        query=message,
        result_summary=result["answer"][:200],
        sources=result.get("sources", []),
        username=request.current_user.get("username", ""),
        role=request.current_user["role"],
        department=request.current_user.get("department", ""),
        action="rag_query",
        ip_address=request.remote_addr,
        duration_ms=_duration
    )

    return jsonify({
        "session_id": session_id,
        "answer": result["answer"],
        "mode": "rag",
        "sources": result.get("sources", [])
    })


@app.route('/search', methods=['POST'])
@require_gateway_auth
def search():
    """
    混合检索接口 - 供 Dify 工作流调用

    请求体:
    {
        "query": "查询文本",
        "top_k": 5  // 可选，默认5
    }

    返回:
    {
        "contexts": ["文档1", "文档2", ...],
        "metadatas": [{"source": "文件名", ...}, ...],
        "scores": [0.95, 0.89, ...]
    }
    """
    data = request.json
    query = data.get('query', '')
    top_k = data.get('top_k', 5)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    # 获取用户权限用于过滤
    allowed_levels = auth_manager.get_user_permissions(request.current_user["role"])
    
    # 获取允许访问的 collection 列表 (用于多向量库)
    try:
        from auth.gateway import get_accessible_collections
        role = request.current_user["role"]
        department = request.current_user.get("department", "")
        allowed_collections = get_accessible_collections(role, department, "read")
    except ImportError:
        allowed_collections = None

    results = search_hybrid(query, top_k=top_k, allowed_levels=allowed_levels, allowed_collections=allowed_collections)

    return jsonify({
        'contexts': results['documents'][0],
        'metadatas': results['metadatas'][0],
        'scores': results['distances'][0]
    })


@app.route('/sessions', methods=['GET'])
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


@app.route('/history/<session_id>', methods=['GET'])
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
    user_id = request.current_user["user_id"]

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权访问此会话"}), 403

    history = session_manager.get_history(session_id, limit=100)

    return jsonify({"history": history})


@app.route('/session/<session_id>', methods=['DELETE'])
@require_gateway_auth
def delete_session(session_id):
    """删除会话"""
    user_id = request.current_user["user_id"]

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权删除此会话"}), 403

    session_manager.delete_session(session_id)

    return jsonify({"success": True, "message": "会话已删除"})


@app.route('/clear/<session_id>', methods=['POST'])
@require_gateway_auth
def clear_history(session_id):
    """清空会话历史（保留会话）"""
    user_id = request.current_user["user_id"]

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权操作此会话"}), 403

    session_manager.clear_history(session_id)

    return jsonify({"success": True, "message": "历史已清空"})


@app.route('/stats', methods=['GET'])
@require_gateway_auth
@require_role('admin')
def get_stats():
    """获取系统统计信息（仅管理员）"""
    return jsonify(session_manager.get_stats())


@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "knowledge_base": "多向量库模式 (按集合提供服务)",
        "bm25_index": "动态按需加载",
        "mode": "Agentic RAG"
    })


# ==================== 认证 API ====================
# 注意：登录和注册由后端网关处理，这里只提供用户信息查询

@app.route('/auth/me', methods=['GET'])
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


# ==================== 多向量库管理 API ====================

# 导入多向量库管理器
try:
    from knowledge.manager import get_kb_manager, KnowledgeBaseManager
    from knowledge.router import get_kb_router, route_query
    from auth.gateway import (
        get_accessible_collections, check_collection_permission,
        can_create_collection, can_delete_collection,
        require_collection_permission
    )
    HAS_MULTI_KB = True
except ImportError as e:
    print(f"警告: 多向量库模块导入失败: {e}")
    HAS_MULTI_KB = False


if HAS_MULTI_KB:
    kb_manager = get_kb_manager()
    kb_router = get_kb_router()


    @app.route('/collections', methods=['GET'])
    @require_gateway_auth
    def list_collections():
        """
        获取用户可访问的向量库列表

        返回:
        {
            "collections": [
                {
                    "name": "public_kb",
                    "display_name": "公开知识库",
                    "document_count": 100,
                    "department": "",
                    "can_write": true,
                    "can_delete": false
                }
            ]
        }
        """
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


    @app.route('/collections', methods=['POST'])
    @require_gateway_auth
    def create_collection():
        """
        创建新向量库

        请求体:
        {
            "name": "dept_newdept",
            "display_name": "新部门知识库",
            "department": "newdept",
            "description": "描述"
        }

        权限: 仅管理员
        """
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


    @app.route('/collections/<kb_name>', methods=['DELETE'])
    @require_gateway_auth
    def delete_collection(kb_name):
        """
        删除向量库

        权限: 仅管理员
        """
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


    @app.route('/collections/<kb_name>/documents', methods=['GET'])
    @require_gateway_auth
    def list_collection_documents(kb_name):
        """
        获取向量库中的文档列表

        权限: 有读权限的用户
        """
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


    @app.route('/documents/sync', methods=['POST'])
    @require_gateway_auth
    def sync_documents():
        """
        触发文档向量化同步

        请求体:
        {
            "collection": "向量库名称"  // 可选，不传则同步所有有权限的库
        }

        权限:
        - admin: 可同步任意向量库
        - manager: 只能同步本部门向量库
        - user: 无同步权限
        """
        user = request.current_user
        role = user["role"]
        department = user.get("department", "")

        data = request.json or {}
        target_collection = data.get('collection')

        # 确定要同步的向量库
        if target_collection:
            # 检查权限
            if not check_collection_permission(role, department, target_collection, "sync"):
                return jsonify({
                    "error": "权限不足",
                    "message": f"您没有权限同步向量库 '{target_collection}'"
                }), 403
            collections_to_sync = [target_collection]
        else:
            # 同步所有有权限的向量库
            collections_to_sync = get_accessible_collections(role, department, "sync")

        if not collections_to_sync:
            return jsonify({"error": "没有可同步的向量库"}), 400

        # 执行同步（调用现有的同步逻辑）
        results = []
        for coll_name in collections_to_sync:
            try:
                # 确定向量库对应的文档目录
                if coll_name == "public_kb":
                    doc_dir = os.path.join(DOCUMENTS_PATH, "public")
                else:
                    dept_name = coll_name.replace("dept_", "")
                    doc_dir = os.path.join(DOCUMENTS_PATH, "dept_" + dept_name)

                # 这里暂时返回模拟结果，实际需要调用向量化函数
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


    @app.route('/kb/route', methods=['POST'])
    @require_gateway_auth
    def test_routing():
        """
        测试知识库路由（调试用）

        请求体:
        {
            "query": "查询内容"
        }
        """
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


# ==================== Graph RAG API ====================

# 尝试导入 Graph RAG 组件
try:
    from config import USE_GRAPH_RAG
except ImportError:
    USE_GRAPH_RAG = False

try:
    from graph import get_graph_manager, GraphRAG
    HAS_GRAPH_RAG = True
except ImportError:
    HAS_GRAPH_RAG = False
    print("提示: Graph RAG 模块未安装，图谱 API 不可用")


@app.route('/graph/search', methods=['POST'])
@require_gateway_auth
def graph_search():
    """
    图谱检索接口

    请求体:
    {
        "query": "查询内容",
        "top_k": 5,
        "depth": 2
    }
    """
    if not HAS_GRAPH_RAG or not USE_GRAPH_RAG:
        return jsonify({
            "error": "Graph RAG 功能未启用",
            "hint": "请在 config.py 中配置 Neo4j 并设置 USE_GRAPH_RAG=True"
        }), 400

    data = request.get_json()
    query = data.get('query', '')
    top_k = data.get('top_k', 5)
    depth = data.get('depth', 2)

    if not query:
        return jsonify({"error": "缺少 query 参数"}), 400

    try:
        rag = GraphRAG()
        result = rag.search(query, top_k=top_k, graph_depth=depth)

        return jsonify({
            "answer": result.answer,
            "entities": result.entities,
            "has_graph_context": bool(result.graph_context),
            "sources": result.sources,
            "graph_context": result.graph_context[:500] if result.graph_context else None
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/graph/build', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def build_graph():
    """
    重建图谱索引

    从现有知识库文档中提取实体和关系，构建知识图谱
    """
    if not HAS_GRAPH_RAG or not USE_GRAPH_RAG:
        return jsonify({
            "error": "Graph RAG 功能未启用",
            "hint": "请在 config.py 中配置 Neo4j 并设置 USE_GRAPH_RAG=True"
        }), 400

    try:
        from rag_demo import rebuild_knowledge_graph

        success = rebuild_knowledge_graph(verbose=True)

        if success:
            return jsonify({
                "status": "success",
                "message": "知识图谱构建完成"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "知识图谱构建失败，请检查 Neo4j 连接"
            }), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/graph/stats', methods=['GET'])
@require_gateway_auth
def graph_stats():
    """获取图谱统计信息"""
    if not HAS_GRAPH_RAG or not USE_GRAPH_RAG:
        return jsonify({
            "enabled": False,
            "message": "Graph RAG 功能未启用"
        })

    try:
        gm = get_graph_manager()
        if not gm or not gm.connected:
            return jsonify({
                "enabled": True,
                "connected": False,
                "message": "无法连接到 Neo4j"
            })

        stats = gm.get_stats()
        gm.close()

        return jsonify({
            "enabled": True,
            "connected": True,
            "nodes": stats['nodes'],
            "edges": stats['edges'],
            "types": stats['types']
        })

    except Exception as e:
        return jsonify({
            "enabled": True,
            "connected": False,
            "error": str(e)
        })


# ==================== 审计日志 API ====================

@app.route('/audit/logs', methods=['GET'])
@require_gateway_auth
@require_role('admin')
def get_audit_logs():
    """
    获取审计日志（仅管理员）

    参数:
        user_id: 按用户过滤（可选）
        action: 按操作类型过滤（可选）
        limit: 返回数量（默认100）
        days: 最近N天（默认7）
    """
    user_id = request.args.get('user_id')
    action = request.args.get('action')
    limit = int(request.args.get('limit', 100))
    days = int(request.args.get('days', 7))

    if user_id:
        logs = audit_logger.get_user_logs(user_id, limit=limit)
    elif action:
        logs = audit_logger.get_recent_logs(limit=limit, action=action)
    else:
        logs = audit_logger.get_recent_logs(limit=limit)

    return jsonify({"logs": logs})


# ==================== 知识库同步 API ====================

# 导入同步服务
try:
    from knowledge.sync import KnowledgeSyncService, SyncStatus, ChangeType
    HAS_SYNC_SERVICE = True
except ImportError as e:
    print(f"警告: 知识库同步服务导入失败: {e}")
    HAS_SYNC_SERVICE = False

# 初始化同步服务
sync_service = None
if HAS_SYNC_SERVICE:
    try:
        sync_service = KnowledgeSyncService(
            documents_path=DOCUMENTS_PATH,
            db_path="./data/sync_data.db"
        )
        print("✓ 知识库同步服务已初始化")
    except Exception as e:
        print(f"✗ 知识库同步服务初始化失败: {e}")


@app.route('/sync', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def trigger_sync():
    """
    手动触发知识库同步

    请求体 (可选):
    {
        "full_sync": false  // 是否全量同步，默认false（增量同步）
    }

    返回:
    {
        "status": "completed",
        "documents_processed": 5,
        "documents_added": 2,
        "documents_modified": 3,
        "documents_deleted": 0,
        "errors": []
    }
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    data = request.json or {}
    full_sync = data.get('full_sync', False)

    try:
        result = sync_service.sync_now()
        return jsonify(result.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/sync/status', methods=['GET'])
@require_gateway_auth
def get_sync_status():
    """
    获取同步状态

    返回:
    {
        "monitoring": true,
        "last_sync": {...},
        "statistics": {...}
    }
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({
            "enabled": False,
            "message": "同步服务未启用"
        })

    # 获取最近同步历史
    history = sync_service.db.get_sync_history(limit=5)

    # 获取统计信息
    all_hashes = sync_service.db.get_all_document_hashes()

    # 获取未处理的变更
    unprocessed_changes = sync_service.db.get_change_logs(limit=100, processed=False)

    return jsonify({
        "enabled": True,
        "monitoring": sync_service.is_running(),
        "documents_tracked": len(all_hashes),
        "unprocessed_changes": len(unprocessed_changes),
        "last_sync": history[0] if history else None,
        "recent_syncs": history
    })


@app.route('/sync/history', methods=['GET'])
@require_gateway_auth
def get_sync_history():
    """
    获取同步历史

    参数:
        limit: 返回数量（默认20）
        days: 最近N天（默认30）

    返回:
    {
        "history": [...]
    }
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    limit = int(request.args.get('limit', 20))
    days = int(request.args.get('days', 30))

    history = sync_service.db.get_sync_history(limit=limit)

    return jsonify({"history": history})


@app.route('/sync/changes', methods=['GET'])
@require_gateway_auth
def get_change_logs():
    """
    获取变更日志

    参数:
        limit: 返回数量（默认50）
        processed: 是否已处理（可选）
        days: 最近N天（默认30）

    返回:
    {
        "changes": [...]
    }
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    limit = int(request.args.get('limit', 50))
    days = int(request.args.get('days', 30))
    processed = request.args.get('processed')

    if processed is not None:
        processed = processed.lower() == 'true'

    changes = sync_service.db.get_change_logs(limit=limit, processed=processed, days=days)

    return jsonify({"changes": changes})


@app.route('/sync/start', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def start_sync_monitor():
    """启动文件监控"""
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    if sync_service.is_running():
        return jsonify({"message": "文件监控已在运行"})

    success = sync_service.start()
    if success:
        return jsonify({"message": "文件监控已启动"})
    else:
        return jsonify({"error": "启动文件监控失败"}), 500


@app.route('/sync/stop', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def stop_sync_monitor():
    """停止文件监控"""
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    sync_service.stop()
    return jsonify({"message": "文件监控已停止"})


# ==================== 文档管理 API ====================

from werkzeug.utils import secure_filename

# 允许的文件类型
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@app.route('/documents/upload', methods=['POST'])
@require_gateway_auth
def upload_document():
    """
    上传文件到知识库

    请求格式: multipart/form-data
    - file: 上传的文件
    - collection: 目标向量库 (public_kb/dept_finance/dept_hr/...)

    权限:
    - admin: 可上传到任意向量库
    - manager: 只能上传到本部门向量库
    - user: 无上传权限
    """
    from auth.gateway import check_collection_permission, can_create_collection

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
    # 将向量库名转换为目录名 (public_kb -> public, dept_finance -> dept_finance)
    if collection == 'public_kb':
        target_subdir = 'public'
    else:
        target_subdir = collection  # dept_finance, dept_hr, etc.

    target_dir = os.path.join(DOCUMENTS_PATH, target_subdir)
    os.makedirs(target_dir, exist_ok=True)

    # 安全文件名 + 处理重名
    filename = secure_filename(file.filename)
    if not filename:  # secure_filename 可能返回空字符串
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


@app.route('/documents/list', methods=['GET'])
@require_gateway_auth
def list_documents():
    """
    获取文档列表

    参数:
        collection: 过滤向量库 (可选)

    权限:
    - admin: 可查看所有
    - manager/user: 只能查看 public + 本部门
    """
    from auth.gateway import get_accessible_collections

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

    # 要扫描的目录
    collections_to_scan = [filter_collection] if filter_collection else accessible_collections

    documents = []
    supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}

    for collection in collections_to_scan:
        # 转换向量库名为目录名
        if collection == 'public_kb':
            subdir = 'public'
        else:
            subdir = collection

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
                    "collection": collection,
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


@app.route('/documents/<path:doc_path>', methods=['DELETE'])
@require_gateway_auth
def delete_document(doc_path):
    """
    删除文档

    参数:
        doc_path: 文档路径，格式为 "collection/filename" 或 "subdir/filename"

    权限:
    - admin: 可删除任意文档
    - manager: 只能删除本部门文档
    - user: 无删除权限
    """
    from auth.gateway import check_collection_permission

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


# ==================== 订阅与通知 API ====================

@app.route('/subscribe', methods=['POST'])
@require_gateway_auth
def subscribe_document():
    """
    订阅文档变更通知

    请求体:
    {
        "document_id": "xxx.pdf"  // 可选，不填则订阅所有文档
    }
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    user_id = request.current_user["user_id"]
    data = request.json or {}
    document_id = data.get('document_id')
    document_name = data.get('document_name')

    sync_service.db.subscribe(user_id, document_id, document_name)

    if document_id:
        message = f"已订阅文档: {document_id}"
    else:
        message = "已订阅所有文档变更通知"

    return jsonify({"success": True, "message": message})


@app.route('/subscribe', methods=['DELETE'])
@require_gateway_auth
def unsubscribe_document():
    """
    取消订阅

    请求体:
    {
        "document_id": "xxx.pdf"  // 可选，不填则取消所有订阅
    }
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    user_id = request.current_user["user_id"]
    data = request.json or {}
    document_id = data.get('document_id')

    sync_service.db.unsubscribe(user_id, document_id)

    return jsonify({"success": True, "message": "已取消订阅"})


@app.route('/subscriptions', methods=['GET'])
@require_gateway_auth
def get_subscriptions():
    """获取当前用户的订阅列表"""
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    user_id = request.current_user["user_id"]

    conn = sqlite3.connect(sync_service.db.db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT document_id, document_name, created_at
        FROM subscriptions WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()

    subscriptions = [
        {
            "document_id": row[0],
            "document_name": row[1],
            "created_at": row[2]
        }
        for row in rows
    ]

    return jsonify({"subscriptions": subscriptions})


@app.route('/notifications', methods=['GET'])
@require_gateway_auth
def get_notifications():
    """
    获取用户通知

    参数:
        unread_only: 是否只显示未读（默认false）
    """
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    user_id = request.current_user["user_id"]
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'

    notifications = sync_service.db.get_notifications(user_id, unread_only)

    return jsonify({"notifications": notifications})


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@require_gateway_auth
def mark_notification_read(notification_id):
    """标记通知为已读"""
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    sync_service.db.mark_notification_read(notification_id)

    return jsonify({"success": True, "message": "已标记为已读"})


@app.route('/notifications/read-all', methods=['POST'])
@require_gateway_auth
def mark_all_notifications_read():
    """标记所有通知为已读"""
    if not HAS_SYNC_SERVICE or not sync_service:
        return jsonify({"error": "同步服务未启用"}), 503

    user_id = request.current_user["user_id"]

    conn = sqlite3.connect(sync_service.db.db_path)
    cursor = conn.cursor()
    cursor.execute('UPDATE notifications SET read = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "所有通知已标记为已读"})


# ==================== 题库维护 API ====================

# 导入题库分析模块
try:
    from exam_pkg.analysis import ExamAnalysisDB, QuestionMaintenanceService, ExamAnalysisService
    exam_analysis_db = ExamAnalysisDB("./data/exam_analysis.db")
    maintenance_service = QuestionMaintenanceService(exam_analysis_db)
    analysis_service = ExamAnalysisService(exam_analysis_db)
    HAS_EXAM_ANALYSIS = True
except ImportError as e:
    print(f"警告: 题库分析模块导入失败: {e}")
    HAS_EXAM_ANALYSIS = False

if HAS_EXAM_ANALYSIS:
    @app.route('/questions/link-document', methods=['POST'])
    @require_gateway_auth
    def link_question_to_document():
        """建立题目-制度关联"""
        data = request.get_json()

        question_id = data.get('question_id')
        question_type = data.get('question_type')  # choice/blank/short_answer
        exam_id = data.get('exam_id')
        document_id = data.get('document_id')
        document_name = data.get('document_name', '')
        chapter = data.get('chapter', '')
        key_points = data.get('key_points', [])
        relevance_score = data.get('relevance_score', 1.0)

        if not all([question_id, question_type, exam_id, document_id]):
            return jsonify({"error": "缺少必要参数"}), 400

        try:
            link_id = maintenance_service.link_question_to_document(
                question_id=question_id,
                question_type=question_type,
                exam_id=exam_id,
                document_id=document_id,
                document_name=document_name,
                chapter=chapter,
                key_points=key_points,
                relevance_score=relevance_score
            )
            return jsonify({
                "success": True,
                "link_id": link_id,
                "message": "题目-制度关联已建立"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/questions/link-knowledge', methods=['POST'])
    @require_gateway_auth
    def link_question_to_knowledge():
        """建立题目-知识点关联"""
        data = request.get_json()

        question_id = data.get('question_id')
        question_type = data.get('question_type')
        exam_id = data.get('exam_id')
        knowledge_point = data.get('knowledge_point')
        weight = data.get('weight', 1.0)

        if not all([question_id, question_type, exam_id, knowledge_point]):
            return jsonify({"error": "缺少必要参数"}), 400

        try:
            link_id = maintenance_service.link_question_to_knowledge(
                question_id=question_id,
                question_type=question_type,
                exam_id=exam_id,
                knowledge_point=knowledge_point,
                weight=weight
            )
            return jsonify({
                "success": True,
                "link_id": link_id,
                "message": "题目-知识点关联已建立"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/questions/affected', methods=['GET'])
    @require_gateway_auth
    def get_affected_questions():
        """获取受影响的题目列表"""
        document_id = request.args.get('document_id')

        try:
            affected = maintenance_service.get_affected_questions(document_id)
            return jsonify({
                "success": True,
                "affected_questions": affected,
                "total": len(affected)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/questions/<question_id>/review', methods=['POST'])
    @require_gateway_auth
    def review_affected_question(question_id):
        """审核受影响的题目"""
        data = request.get_json()
        question_type = data.get('question_type')
        exam_id = data.get('exam_id')
        action = data.get('action')  # confirm/update/disable

        if not all([question_type, exam_id, action]):
            return jsonify({"error": "缺少必要参数"}), 400

        if action not in ['confirm', 'update', 'disable']:
            return jsonify({"error": "无效的审核动作"}), 400

        try:
            result = maintenance_service.review_affected_question(
                question_id=question_id,
                question_type=question_type,
                exam_id=exam_id,
                action=action
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/documents/<document_id>/questions', methods=['GET'])
    @require_gateway_auth
    def get_document_questions(document_id):
        """获取制度文档关联的题目"""
        try:
            questions = exam_analysis_db.get_document_questions(document_id)
            return jsonify({
                "success": True,
                "document_id": document_id,
                "questions": questions,
                "total": len(questions)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/documents/<document_id>/versions', methods=['GET'])
    @require_gateway_auth
    def get_document_versions(document_id):
        """获取制度版本历史"""
        limit = request.args.get('limit', 10, type=int)

        try:
            versions = exam_analysis_db.get_document_versions(document_id, limit)
            return jsonify({
                "success": True,
                "document_id": document_id,
                "versions": versions,
                "total": len(versions)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/knowledge-points', methods=['GET'])
    @require_gateway_auth
    def get_knowledge_points():
        """获取知识点列表"""
        category = request.args.get('category')

        try:
            points = exam_analysis_db.get_knowledge_points(category)
            return jsonify({
                "success": True,
                "knowledge_points": points,
                "total": len(points)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/questions/suggestions', methods=['GET'])
    @require_gateway_auth
    def get_question_suggestions():
        """获取新题建议"""
        document_id = request.args.get('document_id')
        status = request.args.get('status')

        try:
            suggestions = exam_analysis_db.get_question_suggestions(document_id, status)
            return jsonify({
                "success": True,
                "suggestions": suggestions,
                "total": len(suggestions)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    # ==================== 整卷分析 API ====================

    @app.route('/exam/<exam_id>/analyze', methods=['POST'])
    @require_gateway_auth
    def analyze_exam_paper(exam_id):
        """整卷分析"""
        data = request.get_json()

        grade_report = data.get('grade_report')
        question_knowledge_map = data.get('question_knowledge_map')

        if not grade_report:
            return jsonify({"error": "缺少批阅报告"}), 400

        try:
            report = analysis_service.analyze_exam_paper(
                grade_report=grade_report,
                question_knowledge_map=question_knowledge_map
            )
            return jsonify({
                "success": True,
                "report": asdict(report)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/analysis/<report_id>', methods=['GET'])
    @require_gateway_auth
    def get_analysis_report(report_id):
        """获取分析报告"""
        try:
            report = analysis_service.get_analysis_report(report_id)
            if not report:
                return jsonify({"error": "报告不存在"}), 404
            return jsonify({
                "success": True,
                "report": report
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/analysis/list', methods=['GET'])
    @require_gateway_auth
    def list_analysis_reports():
        """获取分析报告列表"""
        exam_id = request.args.get('exam_id')
        limit = request.args.get('limit', 20, type=int)

        try:
            reports = analysis_service.list_analysis_reports(exam_id, limit)
            return jsonify({
                "success": True,
                "reports": reports,
                "total": len(reports)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/questions/<question_id>/knowledge-points', methods=['GET'])
    @require_gateway_auth
    def get_question_knowledge_points(question_id):
        """获取题目关联的知识点"""
        try:
            points = exam_analysis_db.get_question_knowledge_points(question_id)
            return jsonify({
                "success": True,
                "question_id": question_id,
                "knowledge_points": points,
                "total": len(points)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ==================== 版本管理 API ====================

# 导入版本管理模块
try:
    from knowledge.lifecycle import DocumentLifecycleManager, get_lifecycle_manager
    from knowledge.diff import DocumentDiffAnalyzer, get_diff_analyzer
    HAS_VERSION_MANAGEMENT = True
    lifecycle_manager = get_lifecycle_manager()
    diff_analyzer = get_diff_analyzer()
except ImportError as e:
    print(f"警告: 版本管理模块导入失败: {e}")
    HAS_VERSION_MANAGEMENT = False

if HAS_VERSION_MANAGEMENT:
    @app.route('/documents/<collection>/<path:doc_path>/deprecate', methods=['POST'])
    @require_gateway_auth
    def deprecate_document_api(collection, doc_path):
        """
        废止文档（软删除）

        权限: admin 或 manager（本部门）

        请求体:
        {
            "reason": "制度已更新"
        }
        """
        user = request.current_user

        # 权限检查
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

        result = lifecycle_manager.deprecate_document(
            collection=collection,
            document_id=doc_path,
            reason=reason,
            deprecated_by=user.get('user_id', '')
        )

        # 审计日志
        audit_logger.log(
            user_id=user['user_id'],
            action='deprecate_document',
            resource=f"{collection}/{doc_path}",
            details={"reason": reason, "affected_questions": len(result.get('affected_questions', []))}
        )

        return jsonify(result)

    @app.route('/documents/<collection>/<path:doc_path>/restore', methods=['POST'])
    @require_gateway_auth
    def restore_document_api(collection, doc_path):
        """
        恢复已废止的文档

        权限: admin 或 manager（本部门）
        """
        user = request.current_user

        # 权限检查
        if not check_collection_permission(user['role'], user.get('department', ''), collection, 'delete'):
            return jsonify({"error": "权限不足"}), 403

        result = lifecycle_manager.restore_document(
            collection=collection,
            document_id=doc_path,
            restored_by=user.get('user_id', '')
        )

        return jsonify(result)

    @app.route('/documents/<collection>/<path:doc_path>/versions', methods=['GET'])
    @require_gateway_auth
    def get_document_versions_api(collection, doc_path):
        """
        获取文档版本历史

        所有用户可查看（只能看到有权限访问的向量库）
        """
        # 检查读权限
        user = request.current_user
        if not check_collection_permission(user['role'], user.get('department', ''), collection, 'read'):
            return jsonify({"error": "权限不足"}), 403

        limit = request.args.get('limit', 10, type=int)

        history = lifecycle_manager.get_document_history(collection, doc_path, limit)

        return jsonify({
            "success": True,
            "document_id": doc_path,
            "collection": collection,
            "versions": [v.to_dict() for v in history],
            "total": len(history)
        })

    @app.route('/documents/<collection>/<path:doc_path>/info', methods=['GET'])
    @require_gateway_auth
    def get_document_info_api(collection, doc_path):
        """
        获取文档当前状态信息
        """
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

    @app.route('/documents/deprecated', methods=['GET'])
    @require_gateway_auth
    def list_deprecated_documents_api():
        """
        列出已废止的文档

        参数:
            collection: 过滤向量库（可选）
            limit: 返回数量（默认50）
        """
        user = request.current_user
        collection = request.args.get('collection')
        limit = request.args.get('limit', 50, type=int)

        # 如果指定了collection，检查权限
        if collection:
            if not check_collection_permission(user['role'], user.get('department', ''), collection, 'read'):
                return jsonify({"error": "权限不足"}), 403

        deprecated_list = lifecycle_manager.list_deprecated_documents(collection, limit)

        return jsonify({
            "success": True,
            "documents": [d.to_dict() for d in deprecated_list],
            "total": len(deprecated_list)
        })

    @app.route('/search/version-aware', methods=['POST'])
    @require_gateway_auth
    def version_aware_search_api():
        """
        版本感知检索

        执行检索时自动过滤废止版本，并返回相关废止版本提示

        请求体:
        {
            "query": "查询内容",
            "top_k": 5,
            "include_deprecated": false
        }
        """
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

    @app.route('/documents/<collection>/<path:doc_path>/diff', methods=['POST'])
    @require_gateway_auth
    def compare_document_versions_api(collection, doc_path):
        """
        对比文档版本差异

        请求体:
        {
            "old_chunks": [...],  # 可选，不传则从向量库获取
            "new_chunks": [...]   # 新文档chunks
        }
        """
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

            # 转换格式
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
        diff_result = diff_analyzer.compute_diff(old_chunks, new_chunks)

        return jsonify({
            "success": True,
            "document_id": doc_path,
            "collection": collection,
            "diff": diff_result.to_dict()
        })


# ==================== 纲要生成与关联推荐 API ====================

# 导入纲要生成模块
try:
    from services.outline import OutlineDB, OutlineGenerator, RecommendationService
    outline_db = OutlineDB("./data/outline_cache.db")
    outline_generator = OutlineGenerator(outline_db, DOCUMENTS_PATH)
    recommendation_service = RecommendationService(
        outline_db, DOCUMENTS_PATH, collection, embedding_model
    )
    HAS_OUTLINE_SERVICE = True
except ImportError as e:
    print(f"警告: 纲要生成模块导入失败: {e}")
    HAS_OUTLINE_SERVICE = False

if HAS_OUTLINE_SERVICE:
    @app.route('/outline', methods=['POST'])
    @require_gateway_auth
    def generate_outline():
        """生成文档纲要"""
        data = request.get_json()
        document_id = data.get('document_id')
        force = data.get('force', False)

        if not document_id:
            return jsonify({"error": "缺少 document_id 参数"}), 400

        try:
            outline = outline_generator.generate_outline(document_id, force)
            return jsonify({
                "success": True,
                "outline": outline.to_dict()
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/outline/<path:document_id>', methods=['GET'])
    @require_gateway_auth
    def get_outline(document_id):
        """获取已生成的纲要"""
        try:
            outline = outline_db.get_outline(document_id)
            if not outline:
                return jsonify({"error": "纲要不存在，请先生成"}), 404
            return jsonify({
                "success": True,
                "outline": outline.to_dict()
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/outline/<path:document_id>/export', methods=['GET'])
    @require_gateway_auth
    def export_outline(document_id):
        """导出纲要"""
        format_type = request.args.get('format', 'json')  # json/markdown/markmap

        try:
            outline = outline_db.get_outline(document_id)
            if not outline:
                return jsonify({"error": "纲要不存在，请先生成"}), 404

            content = outline_generator.export_outline(outline, format_type)

            # 根据格式设置响应类型
            if format_type == 'json':
                return content, 200, {'Content-Type': 'application/json; charset=utf-8'}
            else:
                return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/outline/<path:document_id>', methods=['DELETE'])
    @require_gateway_auth
    @require_role('admin')
    def delete_outline(document_id):
        """删除纲要缓存"""
        try:
            deleted = outline_db.delete_outline(document_id)
            return jsonify({
                "success": deleted,
                "message": "缓存已删除" if deleted else "缓存不存在"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/outline/list', methods=['GET'])
    @require_gateway_auth
    def list_outlines():
        """获取纲要列表"""
        limit = request.args.get('limit', 50, type=int)
        try:
            outlines = outline_db.list_outlines(limit)
            return jsonify({
                "success": True,
                "outlines": outlines,
                "total": len(outlines)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/outline/batch', methods=['POST'])
    @require_gateway_auth
    def batch_generate_outlines():
        """批量生成纲要"""
        data = request.get_json()
        document_ids = data.get('document_ids', [])
        force = data.get('force', False)

        if not document_ids:
            return jsonify({"error": "缺少 document_ids 参数"}), 400

        try:
            results = outline_generator.batch_generate(document_ids, force)
            return jsonify({
                "success": True,
                "results": {k: v.to_dict() if v else None for k, v in results.items()},
                "total": len(results)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/recommend/<path:document_id>', methods=['GET'])
    @require_gateway_auth
    def get_recommendations(document_id):
        """获取关联推荐"""
        top_k = request.args.get('top_k', 5, type=int)
        use_cache = request.args.get('cache', 'true').lower() == 'true'

        try:
            recommendations = recommendation_service.get_recommendations(
                document_id, top_k, use_cache
            )
            return jsonify({
                "success": True,
                "document_id": document_id,
                "recommendations": [r.to_dict() for r in recommendations],
                "total": len(recommendations)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/recommend/compute-vectors', methods=['POST'])
    @require_gateway_auth
    @require_role('admin')
    def compute_all_vectors():
        """计算所有文档向量（管理员）"""
        try:
            count = recommendation_service.compute_all_vectors()
            return jsonify({
                "success": True,
                "message": f"计算了 {count} 个文档的向量"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ==================== 启动入口 ====================

if __name__ == '__main__':
    import os
    dev_mode = os.environ.get('DEV_MODE', '').lower() == 'true'

    print("=" * 60)
    print("RAG API 服务启动")
    print("=" * 60)

    # 使用多向量库管理器获取统计信息
    if HAS_MULTI_KB and kb_manager:
        try:
            total_count = 0
            for c in kb_manager.list_collections():
                try:
                    total_count += kb_manager.get_document_count(c.name)
                except Exception:
                    pass
            print(f"知识库: {total_count} 条记录 (多向量库模式)")
        except Exception as e:
            print(f"知识库: 统计失败 ({e})")
    else:
        try:
            print(f"知识库: {collection.count()} 条记录")
        except Exception:
            print("知识库: 统计失败")

    print(f"BM25 索引: {len(bm25_docs)} 个文档")
    print(f"会话数据库: ./data/sessions.db")
    print()
    print("认证系统:")
    if dev_mode:
        print("  [开发模式] 使用 Header 模拟用户认证")
        print("  设置 Header: X-User-ID, X-User-Name, X-User-Role, X-User-Department")
    else:
        print("  [生产模式] 通过网关注入 Header 认证")
        print("  需要 Header: X-User-ID (必需), X-User-Name, X-User-Role, X-User-Department")
    print("  GET  /auth/me             - 获取当前用户信息")
    print()
    print("角色权限:")
    print("  admin   - 可访问所有向量库，可增删改查、同步")
    print("  manager - 可访问 public + 本部门向量库，可对本部门增删改查、同步")
    print("  user    - 可访问 public + 本部门向量库，只读")
    print()
    if HAS_MULTI_KB:
        print("多向量库管理 API:")
        print("  GET  /collections                    - 获取向量库列表")
        print("  POST /collections                    - 创建向量库 (需管理员)")
        print("  DELETE /collections/<name>           - 删除向量库 (需管理员)")
        print("  GET  /collections/<name>/documents   - 获取向量库文档列表")
        print("  POST /documents/upload               - 上传文档")
        print("  POST /documents/sync                 - 同步向量化")
        print("  DELETE /documents/<collection>/<file> - 删除文档")
        print("  POST /kb/route                       - 测试知识库路由")
        print()
    print("双模式 (需认证):")
    print(f"  /chat - 普通聊天模式 (模型: {CHAT_MODEL})")
    print(f"  /rag  - 知识库问答模式 (模型: {MODEL})")
    print()
    print("API 接口:")
    print("  POST /chat          - 普通聊天")
    print("  POST /rag           - 知识库问答")
    print("  POST /rag/stream    - 知识库问答(SSE)")
    print("  POST /search        - 混合检索 (供 Dify 调用)")
    print("  GET  /sessions      - 获取会话列表")
    print("  GET  /history/<id>  - 获取会话历史")
    print("  DELETE /session/<id> - 删除会话")
    print("  POST /clear/<id>    - 清空历史")
    print("  GET  /stats         - 统计信息 (需管理员)")
    print("  GET  /health        - 健康检查")
    print()
    print("Graph RAG 接口:")
    print("  POST /graph/search  - 图谱检索")
    print("  POST /graph/build   - 重建图谱索引 (需管理员)")
    print("  GET  /graph/stats   - 图谱统计信息")
    print()
    if HAS_OUTLINE_SERVICE:
        print("纲要生成 API:")
        print("  POST /outline                    - 生成文档纲要")
        print("  GET  /outline/<document_id>      - 获取纲要")
        print("  GET  /outline/<document_id>/export?format=json|markdown|markmap - 导出")
        print("  DELETE /outline/<document_id>    - 删除缓存 (需管理员)")
        print("  GET  /outline/list               - 纲要列表")
        print("  POST /outline/batch              - 批量生成")
        print()
        print("关联推荐 API:")
        print("  GET  /recommend/<document_id>    - 获取关联推荐")
        print("  POST /recommend/compute-vectors  - 计算文档向量 (需管理员)")
        print()

    # 导入问答质量闭环模块
    try:
        from services.feedback import FeedbackDB, FeedbackService
        feedback_db = FeedbackDB("./data/feedback.db")
        feedback_service = FeedbackService(feedback_db)
        HAS_FEEDBACK_SERVICE = True
    except ImportError as e:
        print(f"警告: 问答质量闭环模块导入失败: {e}")
        HAS_FEEDBACK_SERVICE = False

    if HAS_FEEDBACK_SERVICE:
        @app.route('/feedback', methods=['POST'])
        @require_gateway_auth
        def submit_feedback():
            """提交反馈"""
            data = request.get_json()

            session_id = data.get('session_id')
            query = data.get('query')
            answer = data.get('answer')
            rating = data.get('rating')  # 1=赞, -1=踩
            sources = data.get('sources', [])
            reason = data.get('reason', '')
            user_id = data.get('user_id', '')

            if not session_id or not query or rating is None:
                return jsonify({"error": "缺少必要参数"}), 400

            if rating not in [1, -1]:
                return jsonify({"error": "rating 必须是 1 或 -1"}), 400

            try:
                result = feedback_service.submit_feedback(
                    session_id=session_id,
                    query=query,
                    answer=answer or "",
                    rating=rating,
                    sources=sources,
                    reason=reason,
                    user_id=user_id
                )
                return jsonify({
                    "success": True,
                    "feedback_id": result['feedback_id'],
                    "faq_suggested": result.get('faq_suggested', False),
                    "suggestion_id": result.get('suggestion_id')
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/feedback/stats', methods=['GET'])
        @require_gateway_auth
        def get_feedback_stats():
            """获取反馈统计"""
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')

            try:
                stats = feedback_db.get_feedback_stats(start_date, end_date)
                return jsonify({
                    "success": True,
                    "stats": stats
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/feedback/list', methods=['GET'])
        @require_gateway_auth
        def get_feedback_list():
            """获取反馈列表"""
            rating = request.args.get('rating', type=int)
            user_id = request.args.get('user_id')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            limit = request.args.get('limit', 100, type=int)

            try:
                feedbacks = feedback_db.get_feedbacks(
                    rating=rating,
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit
                )
                return jsonify({
                    "success": True,
                    "feedbacks": feedbacks,
                    "total": len(feedbacks)
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/reports/weekly', methods=['GET'])
        @require_gateway_auth
        def get_weekly_report():
            """获取周报告"""
            try:
                report = feedback_service.generate_report("weekly")
                return jsonify({
                    "success": True,
                    "report": report.to_dict()
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/reports/monthly', methods=['GET'])
        @require_gateway_auth
        def get_monthly_report():
            """获取月报告"""
            try:
                report = feedback_service.generate_report("monthly")
                return jsonify({
                    "success": True,
                    "report": report.to_dict()
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq', methods=['GET'])
        @require_gateway_auth
        def get_faq_list():
            """获取FAQ列表"""
            status = request.args.get('status')
            limit = request.args.get('limit', 50, type=int)

            try:
                faqs = feedback_db.get_faqs(status=status, limit=limit)
                return jsonify({
                    "success": True,
                    "faqs": faqs,
                    "total": len(faqs)
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq', methods=['POST'])
        @require_gateway_auth
        @require_role('admin')
        def create_faq():
            """新增FAQ（管理员）"""
            data = request.get_json()

            question = data.get('question')
            answer = data.get('answer')

            if not question or not answer:
                return jsonify({"error": "缺少问题或答案"}), 400

            try:
                from services.feedback import FAQ
                faq = FAQ(
                    question=question,
                    answer=answer,
                    source_documents=data.get('source_documents', []),
                    status=data.get('status', 'approved')
                )
                faq_id = feedback_db.add_faq(faq)
                return jsonify({
                    "success": True,
                    "faq_id": faq_id,
                    "message": "FAQ创建成功"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq/<int:faq_id>', methods=['PUT'])
        @require_gateway_auth
        @require_role('admin')
        def update_faq(faq_id):
            """更新FAQ（管理员）"""
            data = request.get_json()

            try:
                updated = feedback_db.update_faq(faq_id, data)
                return jsonify({
                    "success": updated,
                    "message": "FAQ更新成功" if updated else "FAQ不存在"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq/<int:faq_id>', methods=['DELETE'])
        @require_gateway_auth
        @require_role('admin')
        def delete_faq(faq_id):
            """删除FAQ（管理员）"""
            try:
                deleted = feedback_db.delete_faq(faq_id)
                return jsonify({
                    "success": deleted,
                    "message": "FAQ删除成功" if deleted else "FAQ不存在"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq/suggestions', methods=['GET'])
        @require_gateway_auth
        @require_role('admin')
        def get_faq_suggestions():
            """获取FAQ建议列表（管理员）"""
            status = request.args.get('status', 'pending')
            limit = request.args.get('limit', 50, type=int)

            try:
                suggestions = feedback_db.get_faq_suggestions(status=status, limit=limit)
                return jsonify({
                    "success": True,
                    "suggestions": suggestions,
                    "total": len(suggestions)
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq/suggestions/<int:suggestion_id>/approve', methods=['POST'])
        @require_gateway_auth
        @require_role('admin')
        def approve_faq_suggestion(suggestion_id):
            """批准FAQ建议（管理员）"""
            try:
                faq_id = feedback_db.approve_faq_suggestion(suggestion_id)
                if faq_id > 0:
                    return jsonify({
                        "success": True,
                        "faq_id": faq_id,
                        "message": "FAQ建议已批准"
                    })
                else:
                    return jsonify({"error": "建议不存在"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/faq/suggestions/<int:suggestion_id>/reject', methods=['POST'])
        @require_gateway_auth
        @require_role('admin')
        def reject_faq_suggestion(suggestion_id):
            """拒绝FAQ建议（管理员）"""
            try:
                rejected = feedback_db.reject_faq_suggestion(suggestion_id)
                return jsonify({
                    "success": rejected,
                    "message": "FAQ建议已拒绝" if rejected else "建议不存在"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        print("问答质量闭环 API:")
        print("  POST /feedback                   - 提交反馈")
        print("  GET  /feedback/stats             - 反馈统计")
        print("  GET  /feedback/list              - 反馈列表")
        print("  GET  /reports/weekly             - 周报告")
        print("  GET  /reports/monthly            - 月报告")
        print("  GET  /faq                        - FAQ列表")
        print("  POST /faq                        - 新增FAQ (需管理员)")
        print("  PUT  /faq/<id>                   - 更新FAQ (需管理员)")
        print("  DELETE /faq/<id>                 - 删除FAQ (需管理员)")
        print("  GET  /faq/suggestions            - FAQ建议列表 (需管理员)")
        print("  POST /faq/suggestions/<id>/approve - 批准建议 (需管理员)")
        print("  POST /faq/suggestions/<id>/reject - 拒绝建议 (需管理员)")
        print()

    print()
    if HAS_EXAM_API:
        print("出题系统 API:")
        print("  POST /exam/generate       - 生成试卷")
        print("  GET  /exam/list           - 试卷列表")
        print("  GET  /exam/<exam_id>      - 试卷详情")
        print("  PUT  /exam/<exam_id>      - 更新试卷")
        print("  DELETE /exam/<exam_id>    - 删除试卷")
        print("  POST /exam/<exam_id>/submit   - 提交审核")
        print("  POST /exam/<exam_id>/review   - 审核试卷 (需管理员)")
        print("  POST /exam/<exam_id>/grade    - 批阅试卷")
        print("  GET  /exam/report/<report_id> - 批阅报告详情")
        print("  GET  /exam/report/list        - 批阅报告列表")
        print("  GET  /exam/questions/search   - 搜索题目")
        print()
    print("Dify 集成:")
    print("  在 Dify HTTP 节点中使用: POST http://localhost:5001/search")
    print("  请求头: 需通过网关注入用户信息 (X-User-ID, X-User-Role)")
    print()
    if HAS_SYNC_SERVICE:
        print("知识库同步 API:")
        print("  POST /sync              - 手动触发同步 (需管理员)")
        print("  GET  /sync/status       - 获取同步状态")
        print("  GET  /sync/history      - 同步历史记录")
        print("  GET  /sync/changes      - 变更日志")
        print("  POST /sync/start        - 启动文件监控 (需管理员)")
        print("  POST /sync/stop         - 停止文件监控 (需管理员)")
        print()
        print("订阅通知 API:")
        print("  POST /subscribe         - 订阅文档变更")
        print("  DELETE /subscribe       - 取消订阅")
        print("  GET  /subscriptions     - 获取订阅列表")
        print("  GET  /notifications     - 获取通知")
        print("  POST /notifications/<id>/read - 标记已读")
        print("  POST /notifications/read-all  - 全部已读")
        print()
    if HAS_EXAM_ANALYSIS:
        print("题库维护 API:")
        print("  POST /questions/link-document    - 建立题目-制度关联")
        print("  POST /questions/link-knowledge   - 建立题目-知识点关联")
        print("  GET  /questions/affected         - 获取受影响题目")
        print("  POST /questions/<id>/review      - 审核受影响题目")
        print("  GET  /documents/<id>/questions   - 获取制度关联题目")
        print("  GET  /documents/<id>/versions    - 获取制度版本历史")
        print("  GET  /knowledge-points           - 获取知识点列表")
        print("  GET  /questions/suggestions      - 获取新题建议")
        print()
        print("整卷分析 API:")
        print("  POST /exam/<id>/analyze          - 整卷分析")
        print("  GET  /analysis/<report_id>       - 获取分析报告")
        print("  GET  /analysis/list              - 分析报告列表")
        print("  GET  /questions/<id>/knowledge-points - 获取题目知识点")
        print()
    if HAS_VERSION_MANAGEMENT:
        print("版本管理 API:")
        print("  POST /documents/<collection>/<path>/deprecate - 废止文档(软删除)")
        print("  POST /documents/<collection>/<path>/restore   - 恢复文档")
        print("  GET  /documents/<collection>/<path>/versions   - 版本历史")
        print("  GET  /documents/<collection>/<path>/info       - 文档状态信息")
        print("  GET  /documents/deprecated                      - 已废止文档列表")
        print("  POST /search/version-aware                      - 版本感知检索")
        print("  POST /documents/<collection>/<path>/diff        - 版本差异对比")
        print()
    print("=" * 60)

    # 启动同步服务监控（可选）
    if HAS_SYNC_SERVICE and sync_service:
        try:
            # 自动启动文件监控
            # sync_service.start()  # 取消注释以自动启动
            pass
        except Exception as e:
            print(f"同步服务启动失败: {e}")

    # threaded=True 支持多用户同时请求
    # use_reloader=False 禁用热重载，避免并发请求时的 socket 错误
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True, use_reloader=False)
