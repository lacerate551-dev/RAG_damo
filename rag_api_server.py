"""
带会话管理的 RAG API 服务 - 使用 Agentic RAG

提供 REST API 接口供前端和 Dify 工作流调用：
1. POST /chat - 发送消息并获取回复（普通聊天，直接LLM回复）
2. POST /rag - 发送消息并获取回复（知识库问答，使用Agentic RAG）
3. POST /search - 混合检索接口（供 Dify 工作流调用）
4. GET /sessions - 获取用户会话列表
5. DELETE /session/<session_id> - 删除会话
6. GET /history/<session_id> - 获取会话历史

特性：
- 双模式：普通聊天 / 知识库问答
- 多轮对话：记住上下文
- 用户隔离：不同用户会话独立
- 并发支持：多用户同时请求
- Dify 集成：提供 HTTP 检索接口

使用方式：
    python rag_api_server.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os
import pickle
import numpy as np

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session_manager import SessionManager
from agentic_rag import AgenticRAG
from rag_demo import (
    collection, API_KEY, BASE_URL, MODEL,
    embedding_model, reranker, EMBEDDING_MODEL_PATH, RERANK_MODEL_PATH,
    CHROMA_DB_PATH, VECTOR_WEIGHT, BM25_WEIGHT
)
from openai import OpenAI
from rank_bm25 import BM25Okapi
import jieba

# 初始化
app = Flask(__name__)
CORS(app)

# 会话管理器
session_manager = SessionManager(db_path="./sessions.db", session_expire_hours=24)

# Agentic RAG 实例（用于知识库问答）
agentic_rag = AgenticRAG()

# LLM 客户端（用于普通聊天，使用更快的模型）
llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
CHAT_MODEL = "qwen3.5-flash"  # 聊天使用更快的模型

# BM25 索引路径
BM25_INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bm25_index.pkl")

# 加载 BM25 索引
print("加载 BM25 索引...")
try:
    with open(BM25_INDEX_PATH, 'rb') as f:
        bm25_data = pickle.load(f)
    bm25_docs = bm25_data['documents']
    bm25_metas = bm25_data['metadatas']
    bm25_ids = bm25_data['ids']
    tokenized_docs = [list(jieba.cut(doc)) for doc in bm25_docs]
    bm25 = BM25Okapi(tokenized_docs)
    print(f"BM25 索引加载完成: {len(bm25_docs)} 个文档")
except FileNotFoundError:
    print(f"警告: BM25 索引文件未找到: {BM25_INDEX_PATH}")
    print("请先运行 'python rag_demo.py --rebuild' 构建索引")
    bm25 = None
    bm25_docs = []
    bm25_metas = []
    bm25_ids = []


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


def search_vector(query: str, top_k: int = 15) -> dict:
    """向量检索"""
    query_vector = embedding_model.encode(query).tolist()
    return collection.query(query_embeddings=[query_vector], n_results=top_k)


def search_bm25(query: str, top_k: int = 15) -> dict:
    """BM25 检索"""
    if bm25 is None:
        return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

    tokenized_query = list(jieba.cut(query))
    scores = bm25.get_scores(tokenized_query)
    top_indices = np.argsort(scores)[::-1][:top_k]
    return {
        'ids': [[bm25_ids[i] for i in top_indices]],
        'documents': [[bm25_docs[i] for i in top_indices]],
        'metadatas': [[bm25_metas[i] for i in top_indices]],
        'distances': [[float(scores[i]) for i in top_indices]]
    }


def search_hybrid(query: str, top_k: int = 5, candidates: int = 15) -> dict:
    """混合检索 + Rerank"""
    # 向量检索
    vector_results = search_vector(query, candidates)
    # BM25 检索
    bm25_results = search_bm25(query, candidates)
    # RRF 融合
    fused_results = reciprocal_rank_fusion(
        [vector_results, bm25_results],
        [VECTOR_WEIGHT, BM25_WEIGHT]
    )

    # Rerank
    if reranker and fused_results['documents'][0]:
        pairs = [(query, doc) for doc in fused_results['documents'][0]]
        scores = reranker.predict(pairs)
        sorted_indices = np.argsort(scores)[::-1][:top_k]
        return {
            'ids': [[fused_results['ids'][0][i] for i in sorted_indices]],
            'documents': [[fused_results['documents'][0][i] for i in sorted_indices]],
            'metadatas': [[fused_results['metadatas'][0][i] for i in sorted_indices]],
            'distances': [[float(scores[i]) for i in sorted_indices]]
        }

    # 没有 Reranker，直接返回融合结果
    return {
        'ids': [fused_results['ids'][0][:top_k]],
        'documents': [fused_results['documents'][0][:top_k]],
        'metadatas': [fused_results['metadatas'][0][:top_k]],
        'distances': [fused_results['distances'][0][:top_k]]
    }


@app.route('/chat', methods=['POST'])
def chat():
    """
    普通聊天模式 - 直接使用LLM回复，速度快

    请求体:
    {
        "user_id": "用户ID",
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

    user_id = data.get('user_id')
    session_id = data.get('session_id')
    message = data.get('message')

    if not user_id or not message:
        return jsonify({"error": "缺少 user_id 或 message"}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 智能聊天（支持网络搜索）
    result = chat_with_llm(message, history)

    # 保存助手回复
    session_manager.add_message(session_id, "assistant", result["answer"])

    return jsonify({
        "session_id": session_id,
        "answer": result["answer"],
        "mode": "chat",
        "sources": result.get("sources", []),
        "web_searched": result.get("web_searched", False)
    })


@app.route('/rag/stream', methods=['POST'])
def rag_stream():
    """
    知识库问答模式 - SSE 流式返回（包含思考过程日志）

    请求体:
    {
        "user_id": "用户ID",
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
    user_id = data.get('user_id')
    session_id = data.get('session_id')
    message = data.get('message')

    if not user_id or not message:
        return jsonify({"error": "缺少 user_id 或 message"}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

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
                    log_callback=log_callback
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
def rag():
    """
    知识库问答模式 - 使用Agentic RAG检索回复

    请求体:
    {
        "user_id": "用户ID",
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

    user_id = data.get('user_id')
    session_id = data.get('session_id')
    message = data.get('message')

    if not user_id or not message:
        return jsonify({"error": "缺少 user_id 或 message"}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 使用 Agentic RAG 处理
    result = agentic_rag.process(message, verbose=False, history=history)

    # 保存助手回复
    session_manager.add_message(session_id, "assistant", result["answer"])

    return jsonify({
        "session_id": session_id,
        "answer": result["answer"],
        "mode": "rag",
        "sources": result.get("sources", [])
    })


@app.route('/search', methods=['POST'])
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

    results = search_hybrid(query, top_k=top_k)

    return jsonify({
        'contexts': results['documents'][0],
        'metadatas': results['metadatas'][0],
        'scores': results['distances'][0]
    })


@app.route('/sessions', methods=['GET'])
def get_sessions():
    """
    获取用户的会话列表

    参数:
        user_id: 用户ID

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
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

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
def get_history(session_id):
    """
    获取会话历史

    参数:
        user_id: 用户ID（用于验证权限）

    返回:
    {
        "history": [
            {"role": "user/assistant", "content": "...", "created_at": "..."}
        ]
    }
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权访问此会话"}), 403

    history = session_manager.get_history(session_id, limit=100)

    return jsonify({"history": history})


@app.route('/session/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """
    删除会话

    参数:
        user_id: 用户ID（用于验证权限）
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权删除此会话"}), 403

    session_manager.delete_session(session_id)

    return jsonify({"success": True, "message": "会话已删除"})


@app.route('/clear/<session_id>', methods=['POST'])
def clear_history(session_id):
    """
    清空会话历史（保留会话）

    参数:
        user_id: 用户ID（用于验证权限）
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权操作此会话"}), 403

    session_manager.clear_history(session_id)

    return jsonify({"success": True, "message": "历史已清空"})


@app.route('/stats', methods=['GET'])
def get_stats():
    """获取系统统计信息"""
    return jsonify(session_manager.get_stats())


@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "knowledge_base": f"{collection.count()} 条记录",
        "bm25_index": f"{len(bm25_docs)} 个文档" if bm25 else "未加载",
        "mode": "Agentic RAG"
    })


# ==================== Graph RAG API ====================

# 尝试导入 Graph RAG 组件
try:
    from config import USE_GRAPH_RAG
except ImportError:
    USE_GRAPH_RAG = False

try:
    from graph_manager import get_graph_manager
    from graph_rag import GraphRAG
    HAS_GRAPH_RAG = True
except ImportError:
    HAS_GRAPH_RAG = False
    print("提示: Graph RAG 模块未安装，图谱 API 不可用")


@app.route('/graph/search', methods=['POST'])
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


if __name__ == '__main__':
    print("=" * 60)
    print("RAG API 服务启动")
    print("=" * 60)
    print(f"知识库: {collection.count()} 条记录")
    print(f"BM25 索引: {len(bm25_docs)} 个文档")
    print(f"会话数据库: ./sessions.db")
    print()
    print("双模式:")
    print(f"  /chat - 普通聊天模式 (模型: {CHAT_MODEL})")
    print(f"  /rag  - 知识库问答模式 (模型: {MODEL})")
    print()
    print("API 接口:")
    print("  POST /chat          - 普通聊天")
    print("  POST /rag           - 知识库问答")
    print("  POST /search        - 混合检索 (供 Dify 调用)")
    print("  GET  /sessions      - 获取会话列表")
    print("  GET  /history/<id>  - 获取会话历史")
    print("  DELETE /session/<id> - 删除会话")
    print("  POST /clear/<id>    - 清空历史")
    print("  GET  /stats         - 统计信息")
    print("  GET  /health        - 健康检查")
    print()
    print("Graph RAG 接口:")
    print("  POST /graph/search  - 图谱检索")
    print("  POST /graph/build   - 重建图谱索引")
    print("  GET  /graph/stats   - 图谱统计信息")
    print()
    print("Dify 集成:")
    print("  在 Dify HTTP 节点中使用: POST http://localhost:5001/search")
    print("  请求体: {\"query\": \"查询内容\", \"top_k\": 5}")
    print("=" * 60)

    # threaded=True 支持多用户同时请求
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
