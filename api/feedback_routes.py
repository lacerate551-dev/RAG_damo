"""
问答质量闭环 API

路由:
- POST   /feedback                          - 提交反馈
- GET    /feedback/stats                    - 反馈统计
- GET    /feedback/list                     - 反馈列表
- GET    /reports/weekly                    - 周报告
- GET    /reports/monthly                   - 月报告
- GET    /faq                               - FAQ列表
- POST   /faq                               - 新增FAQ (管理员)
- PUT    /faq/<faq_id>                      - 更新FAQ (管理员)
- DELETE /faq/<faq_id>                      - 删除FAQ (管理员)
- GET    /faq/suggestions                   - FAQ建议列表 (管理员)
- POST   /faq/suggestions/<id>/approve      - 批准建议 (管理员)
- POST   /faq/suggestions/<id>/reject       - 拒绝建议 (管理员)
"""

from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth, require_role

feedback_bp = Blueprint('feedback', __name__)

# 延迟初始化：在 Blueprint 注册时通过 app.config 获取
_feedback_db = None
_feedback_service = None


def _get_feedback_db():
    global _feedback_db
    if _feedback_db is None:
        from services.feedback import FeedbackDB
        _feedback_db = FeedbackDB("./data/feedback.db")
    return _feedback_db


def _get_feedback_service():
    global _feedback_service
    if _feedback_service is None:
        from services.feedback import FeedbackService
        _feedback_service = FeedbackService(_get_feedback_db())
    return _feedback_service


@feedback_bp.route('/feedback', methods=['POST'])
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
        feedback_service = _get_feedback_service()
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


@feedback_bp.route('/feedback/stats', methods=['GET'])
@require_gateway_auth
def get_feedback_stats():
    """获取反馈统计"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        feedback_db = _get_feedback_db()
        stats = feedback_db.get_feedback_stats(start_date, end_date)
        return jsonify({
            "success": True,
            "stats": stats
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/feedback/list', methods=['GET'])
@require_gateway_auth
def get_feedback_list():
    """获取反馈列表"""
    rating = request.args.get('rating', type=int)
    user_id = request.args.get('user_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    limit = request.args.get('limit', 100, type=int)

    try:
        feedback_db = _get_feedback_db()
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


@feedback_bp.route('/reports/weekly', methods=['GET'])
@require_gateway_auth
def get_weekly_report():
    """获取周报告"""
    try:
        feedback_service = _get_feedback_service()
        report = feedback_service.generate_report("weekly")
        return jsonify({
            "success": True,
            "report": report.to_dict()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/reports/monthly', methods=['GET'])
@require_gateway_auth
def get_monthly_report():
    """获取月报告"""
    try:
        feedback_service = _get_feedback_service()
        report = feedback_service.generate_report("monthly")
        return jsonify({
            "success": True,
            "report": report.to_dict()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/faq', methods=['GET'])
@require_gateway_auth
def get_faq_list():
    """获取FAQ列表"""
    status = request.args.get('status')
    limit = request.args.get('limit', 50, type=int)

    try:
        feedback_db = _get_feedback_db()
        faqs = feedback_db.get_faqs(status=status, limit=limit)
        return jsonify({
            "success": True,
            "faqs": faqs,
            "total": len(faqs)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/faq', methods=['POST'])
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
        feedback_db = _get_feedback_db()
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


@feedback_bp.route('/faq/<int:faq_id>', methods=['PUT'])
@require_gateway_auth
@require_role('admin')
def update_faq(faq_id):
    """更新FAQ（管理员）"""
    data = request.get_json()

    try:
        feedback_db = _get_feedback_db()
        updated = feedback_db.update_faq(faq_id, data)
        return jsonify({
            "success": updated,
            "message": "FAQ更新成功" if updated else "FAQ不存在"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/faq/<int:faq_id>', methods=['DELETE'])
@require_gateway_auth
@require_role('admin')
def delete_faq(faq_id):
    """删除FAQ（管理员）"""
    try:
        feedback_db = _get_feedback_db()
        deleted = feedback_db.delete_faq(faq_id)
        return jsonify({
            "success": deleted,
            "message": "FAQ删除成功" if deleted else "FAQ不存在"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/faq/suggestions', methods=['GET'])
@require_gateway_auth
@require_role('admin')
def get_faq_suggestions():
    """获取FAQ建议列表（管理员）"""
    status = request.args.get('status', 'pending')
    limit = request.args.get('limit', 50, type=int)

    try:
        feedback_db = _get_feedback_db()
        suggestions = feedback_db.get_faq_suggestions(status=status, limit=limit)
        return jsonify({
            "success": True,
            "suggestions": suggestions,
            "total": len(suggestions)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/faq/suggestions/<int:suggestion_id>/approve', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def approve_faq_suggestion(suggestion_id):
    """批准FAQ建议（管理员）"""
    try:
        feedback_db = _get_feedback_db()
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


@feedback_bp.route('/faq/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def reject_faq_suggestion(suggestion_id):
    """拒绝FAQ建议（管理员）"""
    try:
        feedback_db = _get_feedback_db()
        rejected = feedback_db.reject_faq_suggestion(suggestion_id)
        return jsonify({
            "success": rejected,
            "message": "FAQ建议已拒绝" if rejected else "建议不存在"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
