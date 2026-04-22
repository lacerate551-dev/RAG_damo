"""
纲要生成与关联推荐 API

路由:
- POST   /outline                           - 生成文档纲要
- GET    /outline/<document_id>             - 获取已生成的纲要
- GET    /outline/<document_id>/export      - 导出纲要
- DELETE /outline/<document_id>             - 删除纲要缓存 (管理员)
- GET    /outline/list                      - 纲要列表
- POST   /outline/batch                     - 批量生成纲要
- GET    /recommend/<document_id>           - 获取关联推荐
- POST   /recommend/compute-vectors         - 计算文档向量 (管理员)
"""

from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth, require_role

outline_bp = Blueprint('outline', __name__)

# 延迟初始化
_outline_db = None
_outline_generator = None
_recommendation_service = None


def _get_outline_db():
    global _outline_db
    if _outline_db is None:
        from services.outline import OutlineDB
        _outline_db = OutlineDB("./data/outline_cache.db")
    return _outline_db


def _get_outline_generator():
    global _outline_generator
    if _outline_generator is None:
        from services.outline import OutlineGenerator
        from config import DOCUMENTS_PATH
        _outline_generator = OutlineGenerator(_get_outline_db(), DOCUMENTS_PATH)
    return _outline_generator


def _get_recommendation_service():
    global _recommendation_service
    if _recommendation_service is None:
        from services.outline import RecommendationService
        from config import DOCUMENTS_PATH
        from core.engine import get_engine
        _engine = get_engine()
        _recommendation_service = RecommendationService(
            _get_outline_db(), DOCUMENTS_PATH, _engine.collection, _engine.embedding_model
        )
    return _recommendation_service


@outline_bp.route('/outline', methods=['POST'])
@require_gateway_auth
def generate_outline():
    """生成文档纲要"""
    data = request.get_json()
    document_id = data.get('document_id')
    force = data.get('force', False)

    if not document_id:
        return jsonify({"error": "缺少 document_id 参数"}), 400

    try:
        generator = _get_outline_generator()
        outline = generator.generate_outline(document_id, force)
        return jsonify({
            "success": True,
            "outline": outline.to_dict()
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@outline_bp.route('/outline/<path:document_id>', methods=['GET'])
@require_gateway_auth
def get_outline(document_id):
    """获取已生成的纲要"""
    try:
        outline_db = _get_outline_db()
        outline = outline_db.get_outline(document_id)
        if not outline:
            return jsonify({"error": "纲要不存在，请先生成"}), 404
        return jsonify({
            "success": True,
            "outline": outline.to_dict()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@outline_bp.route('/outline/<path:document_id>/export', methods=['GET'])
@require_gateway_auth
def export_outline(document_id):
    """导出纲要"""
    format_type = request.args.get('format', 'json')  # json/markdown/markmap

    try:
        outline_db = _get_outline_db()
        outline = outline_db.get_outline(document_id)
        if not outline:
            return jsonify({"error": "纲要不存在，请先生成"}), 404

        generator = _get_outline_generator()
        content = generator.export_outline(outline, format_type)

        # 根据格式设置响应类型
        if format_type == 'json':
            return content, 200, {'Content-Type': 'application/json; charset=utf-8'}
        else:
            return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@outline_bp.route('/outline/<path:document_id>', methods=['DELETE'])
@require_gateway_auth
@require_role('admin')
def delete_outline(document_id):
    """删除纲要缓存"""
    try:
        outline_db = _get_outline_db()
        deleted = outline_db.delete_outline(document_id)
        return jsonify({
            "success": deleted,
            "message": "缓存已删除" if deleted else "缓存不存在"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@outline_bp.route('/outline/list', methods=['GET'])
@require_gateway_auth
def list_outlines():
    """获取纲要列表"""
    limit = request.args.get('limit', 50, type=int)
    try:
        outline_db = _get_outline_db()
        outlines = outline_db.list_outlines(limit)
        return jsonify({
            "success": True,
            "outlines": outlines,
            "total": len(outlines)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@outline_bp.route('/outline/batch', methods=['POST'])
@require_gateway_auth
def batch_generate_outlines():
    """批量生成纲要"""
    data = request.get_json()
    document_ids = data.get('document_ids', [])
    force = data.get('force', False)

    if not document_ids:
        return jsonify({"error": "缺少 document_ids 参数"}), 400

    try:
        generator = _get_outline_generator()
        results = generator.batch_generate(document_ids, force)
        return jsonify({
            "success": True,
            "results": {k: v.to_dict() if v else None for k, v in results.items()},
            "total": len(results)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@outline_bp.route('/recommend/<path:document_id>', methods=['GET'])
@require_gateway_auth
def get_recommendations(document_id):
    """获取关联推荐"""
    top_k = request.args.get('top_k', 5, type=int)
    use_cache = request.args.get('cache', 'true').lower() == 'true'

    try:
        rec_service = _get_recommendation_service()
        recommendations = rec_service.get_recommendations(
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


@outline_bp.route('/recommend/compute-vectors', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def compute_all_vectors():
    """计算所有文档向量（管理员）"""
    try:
        rec_service = _get_recommendation_service()
        count = rec_service.compute_all_vectors()
        return jsonify({
            "success": True,
            "message": f"计算了 {count} 个文档的向量"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
