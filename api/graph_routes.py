"""
Graph RAG API

路由:
- POST /graph/search  - 图谱检索
- POST /graph/build   - 重建图谱索引 (管理员)
- GET  /graph/stats   - 图谱统计信息
"""

from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth, require_role

graph_bp = Blueprint('graph', __name__)

# 延迟检测 Graph RAG 可用性
_graph_checked = False
_has_graph_rag = False
_use_graph_rag = False


def _check_graph_rag():
    global _graph_checked, _has_graph_rag, _use_graph_rag
    if not _graph_checked:
        try:
            from config import USE_GRAPH_RAG
            _use_graph_rag = USE_GRAPH_RAG
        except ImportError:
            _use_graph_rag = False

        try:
            from graph import get_graph_manager, GraphRAG  # noqa: F401
            _has_graph_rag = True
        except ImportError:
            _has_graph_rag = False

        _graph_checked = True
    return _has_graph_rag and _use_graph_rag


@graph_bp.route('/graph/search', methods=['POST'])
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
    if not _check_graph_rag():
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
        from graph import GraphRAG
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


@graph_bp.route('/graph/build', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def build_graph():
    """
    重建图谱索引

    从现有知识库文档中提取实体和关系，构建知识图谱
    """
    if not _check_graph_rag():
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


@graph_bp.route('/graph/stats', methods=['GET'])
@require_gateway_auth
def graph_stats():
    """获取图谱统计信息"""
    if not _check_graph_rag():
        return jsonify({
            "enabled": False,
            "message": "Graph RAG 功能未启用"
        })

    try:
        from graph import get_graph_manager
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
