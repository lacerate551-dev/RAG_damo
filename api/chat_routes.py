"""
核心聊天与检索 API

路由:
- POST /chat        - 普通聊天模式
- POST /rag         - 知识库问答模式
- POST /rag/stream  - 知识库问答 SSE 流式返回
- POST /search      - 混合检索接口（供 Dify 调用）
"""

import json
import queue
import threading

import numpy as np
from flask import Blueprint, request, jsonify, Response, current_app
from auth.gateway import require_gateway_auth, get_auth_manager

from auth.security import validate_query, filter_response

chat_bp = Blueprint('chat', __name__)

# 聊天使用更快的模型
CHAT_MODEL = "qwen3.5-flash"


def _get_session_manager():
    return current_app.config['SESSION_MANAGER']


def _get_audit_logger():
    return current_app.config['AUDIT_LOGGER']


def _get_agentic_rag():
    return current_app.config['AGENTIC_RAG']


def _extract_rich_media(contexts: list) -> dict:
    """
    从检索结果提取富媒体信息

    Args:
        contexts: 检索上下文列表

    Returns:
        {"images": [...], "tables": [...], "sections": [...]}
    """
    import json
    images = []
    tables = []
    sections = set()

    for ctx in contexts:
        meta = ctx.get("meta", {})

        # 提取图片（支持 images_json 和 images 两种格式）
        images_data = None
        if meta.get("images_json"):
            try:
                images_data = json.loads(meta["images_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        elif meta.get("images"):
            images_data = meta["images"]

        if images_data:
            for img in images_data:
                images.append({
                    "id": img.get("id"),
                    "caption": img.get("caption", ""),
                    "url": f"/images/{img.get('id')}",
                    "page": meta.get("page"),
                    "source": meta.get("source"),
                    "width": img.get("width"),
                    "height": img.get("height")
                })

        # 提取表格
        if meta.get("is_table") or meta.get("chunk_type") == "table":
            tables.append({
                "id": meta.get("id", ""),
                "markdown": ctx.get("doc", "")[:1000],  # 截取部分
                "page": meta.get("page"),
                "source": meta.get("source")
            })

        # 提取章节
        if meta.get("section_path"):
            sections.add(meta["section_path"])

    return {
        "images": images,
        "tables": tables,
        "sections": list(sections)
    }


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
    agentic_rag = _get_agentic_rag()
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


def search_hybrid(query: str, top_k: int = 5, candidates: int = 15,
                   allowed_levels: list = None, allowed_collections: list = None) -> dict:
    """混合检索 + Rerank，支持多向量库模式"""
    from rag_demo import embedding_model, reranker, collection

    # 尝试使用最新的多数据库管理器
    try:
        from knowledge.manager import get_kb_manager
        kb_manager = get_kb_manager()

        target_kbs = allowed_collections if allowed_collections else ["public_kb"]
        query_vector = embedding_model.encode(query).tolist()

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


# ==================== 路由 ====================

@chat_bp.route('/chat', methods=['POST'])
@require_gateway_auth
def chat():
    """
    普通聊天模式 - 直接使用LLM回复，速度快

    请求体:
    {
        "session_id": "会话ID（首次为null）",
        "message": "消息内容"
    }
    """
    data = request.json
    session_manager = _get_session_manager()

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


@chat_bp.route('/rag/stream', methods=['POST'])
@require_gateway_auth
def rag_stream():
    """
    知识库问答模式 - SSE 流式返回（包含思考过程日志）
    """
    data = request.json
    session_manager = _get_session_manager()
    agentic_rag = _get_agentic_rag()
    auth_manager = get_auth_manager()

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
    user_role = request.current_user["role"]
    user_department = request.current_user.get("department", "")
    allowed_levels = auth_manager.get_user_permissions(user_role)

    # 创建消息队列用于 SSE
    log_queue = queue.Queue()

    def log_callback(event):
        """日志回调，将事件放入队列"""
        log_queue.put(event)

    def generate():
        """生成 SSE 流"""
        try:
            result_holder = {'result': None}

            # 先发送一个开始事件，确认连接正常
            yield f"data: {json.dumps({'type': 'connected', 'message': '开始处理...'}, ensure_ascii=False)}\n\n"

            def process():
                try:
                    result = agentic_rag.process(
                        message,
                        verbose=False,
                        history=history,
                        log_callback=log_callback,
                        allowed_levels=allowed_levels,
                        role=user_role,
                        department=user_department
                    )
                    result_holder['result'] = result
                except Exception as e:
                    import traceback
                    result_holder['error'] = str(e)
                    result_holder['traceback'] = traceback.format_exc()

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
            result = result_holder.get('result')

            # 检查是否有错误
            if 'error' in result_holder:
                error_event = {"type": "error", "message": result_holder['error'], "traceback": result_holder.get('traceback', '')}
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                return

            # 保存助手回复
            if result:
                session_manager.add_message(session_id, "assistant", result["answer"])

                # 提取富媒体信息
                rich_media = _extract_rich_media(result.get("contexts", []))

                # 发送最终结果
                final_event = {
                    "type": "result",
                    "session_id": session_id,
                    "answer": result["answer"],
                    "mode": "rag",
                    "sources": result.get("sources", []),
                    "log_trace": result.get("log_trace", []),
                    # 富媒体字段
                    "images": rich_media["images"],
                    "tables": rich_media["tables"],
                    "sections": rich_media["sections"],
                    # 分类信息
                    "classified": result.get("classified")
                }
                yield f"data: {json.dumps(final_event, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': '处理返回空结果'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            import traceback
            error_event = {"type": "error", "message": str(e), "traceback": traceback.format_exc()}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@chat_bp.route('/rag', methods=['POST'])
@require_gateway_auth
def rag():
    """
    知识库问答模式 - 使用Agentic RAG检索回复
    """
    data = request.json
    session_manager = _get_session_manager()
    agentic_rag = _get_agentic_rag()
    audit_logger = _get_audit_logger()
    auth_manager = get_auth_manager()

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

    # 提取富媒体信息
    rich_media = _extract_rich_media(result.get("contexts", []))

    return jsonify({
        "session_id": session_id,
        "answer": result["answer"],
        "mode": "rag",
        "sources": result.get("sources", []),
        # 富媒体字段
        "images": rich_media["images"],
        "tables": rich_media["tables"],
        "sections": rich_media["sections"],
        # 分类信息（调试用）
        "classified": result.get("classified")
    })


@chat_bp.route('/search', methods=['POST'])
@require_gateway_auth
def search():
    """
    混合检索接口 - 供 Dify 工作流调用
    """
    auth_manager = get_auth_manager()

    data = request.json
    query = data.get('query', '')
    top_k = data.get('top_k', 5)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    # 获取用户权限用于过滤
    allowed_levels = auth_manager.get_user_permissions(request.current_user["role"])

    # 获取允许访问的 collection 列表
    try:
        from auth.gateway import get_accessible_collections
        role = request.current_user["role"]
        department = request.current_user.get("department", "")
        allowed_collections = get_accessible_collections(role, department, "read")
    except ImportError:
        allowed_collections = None

    results = search_hybrid(query, top_k=top_k, allowed_levels=allowed_levels,
                            allowed_collections=allowed_collections)

    return jsonify({
        'contexts': results['documents'][0],
        'metadatas': results['metadatas'][0],
        'scores': results['distances'][0]
    })
