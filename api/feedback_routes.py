"""
问答质量闭环 API

路由:
- POST   /feedback                          - 提交反馈
- GET    /feedback/stats                    - 反馈统计
- GET    /feedback/list                     - 反馈列表
- GET    /feedback/bad-cases                - Bad Case 分析（管理员）
- GET    /feedback/blacklist                - Chunk 黑名单（管理员）
- GET    /reports/weekly                    - 周报告
- GET    /reports/monthly                   - 月报告
- GET    /faq                               - FAQ列表
- POST   /faq                               - 新增FAQ (管理员，需二次确认)
- PUT    /faq/<faq_id>                      - 更新FAQ (管理员)
- DELETE /faq/<faq_id>                      - 删除FAQ (管理员)
- POST   /faq/<faq_id>/approve              - 批准FAQ并同步知识库 (管理员)
- GET    /faq/suggestions                   - FAQ建议列表 (管理员)
- POST   /faq/suggestions/<id>/approve      - 批准建议并同步知识库 (管理员)
- POST   /faq/suggestions/<id>/reject       - 拒绝建议 (管理员)

安全设计（二次确认机制）：
所有 FAQ 入库都需要管理员二次确认，防止错误数据污染知识库：
1. 用户反馈 → FAQ 建议 (pending)
2. 管理员创建 → FAQ 草稿 (draft)
3. 二次确认 → 同步 ChromaDB (approved)

反馈飞轮机制：
1. 用户反馈 → 自动沉淀为 FAQ 建议（复合分数 > 0.5）
2. 管理员批准 → FAQ 同步到 ChromaDB（问题扩写 + 向量化）
3. 检索时 → FAQ 分数加权 + 时间衰减 + 黑名单过滤
4. LLM 生成 → FAQ 作为 Golden Context 融合回答
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
        _feedback_db = FeedbackDB()
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
    """
    新增FAQ（管理员）- 创建后需二次确认同步

    安全设计：
    1. 管理员创建的 FAQ 默认状态为 'draft'
    2. 需要通过 /faq/<id>/approve 接口二次确认
    3. 确认后才同步到 ChromaDB
    """
    data = request.get_json()

    question = data.get('question')
    answer = data.get('answer')

    if not question or not answer:
        return jsonify({"error": "缺少问题或答案"}), 400

    try:
        from services.feedback import FAQ
        feedback_db = _get_feedback_db()

        # 管理员创建也进入 draft 状态，需要二次确认
        faq = FAQ(
            question=question,
            answer=answer,
            source_documents=data.get('source_documents', []),
            status='draft'  # 强制为 draft，需要二次确认
        )
        faq_id = feedback_db.add_faq(faq)

        return jsonify({
            "success": True,
            "faq_id": faq_id,
            "status": "draft",
            "message": "FAQ已创建，请通过 /faq/<id>/approve 接口确认后生效"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/faq/<int:faq_id>/approve', methods=['POST'])
@require_gateway_auth
@require_role('admin')
def approve_faq(faq_id):
    """
    批准FAQ并同步到知识库（管理员二次确认）

    适用于：
    1. 管理员手动创建的 FAQ
    2. 从 FAQ 建议转为正式的 FAQ
    """
    try:
        feedback_db = _get_feedback_db()

        # 检查 FAQ 状态
        faq = feedback_db.get_faq(faq_id)
        if not faq:
            return jsonify({"error": "FAQ不存在"}), 404

        if faq.get('status') == 'approved':
            return jsonify({"success": True, "message": "FAQ已经是批准状态"})

        # 更新状态为 approved
        feedback_db.update_faq(faq_id, {"status": "approved"})

        # 同步到知识库
        feedback_service = _get_feedback_service()
        sync_success = feedback_service._sync_faq_to_knowledge_base(
            faq_id=faq_id,
            question=faq['question'],
            answer=faq['answer']
        )

        return jsonify({
            "success": True,
            "faq_id": faq_id,
            "sync_status": "synced" if sync_success else "sync_failed",
            "message": "FAQ已批准并同步到知识库"
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
    """
    删除FAQ（管理员）- 同步删除向量库数据

    由于 FAQ 存储在独立的集合中，删除时可以精确清理，
    不会影响普通文档向量库。
    """
    try:
        feedback_db = _get_feedback_db()

        # 先获取 FAQ 信息（用于删除向量）
        faq = feedback_db.get_faq(faq_id)

        # 删除数据库记录
        deleted = feedback_db.delete_faq(faq_id)

        if deleted and faq:
            # 同步删除向量库中的 FAQ 向量
            feedback_service = _get_feedback_service()
            feedback_service._delete_faq_vectors(faq_id)

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
    """批准FAQ建议并同步到知识库（管理员）"""
    try:
        feedback_service = _get_feedback_service()
        result = feedback_service.approve_and_sync_faq(suggestion_id)

        if result.get('success'):
            return jsonify({
                "success": True,
                "faq_id": result['faq_id'],
                "sync_status": result.get('sync_status'),
                "message": "FAQ建议已批准并同步到知识库"
            })
        else:
            return jsonify({"error": result.get('error', '批准失败')}), 400
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


# ==================== Bad Case 分析接口 ====================

@feedback_bp.route('/feedback/bad-cases', methods=['GET'])
@require_gateway_auth
@require_role('admin')
def get_bad_cases():
    """
    获取负反馈 Bad Case 列表（管理员）

    用于分析和改进 RAG 系统：
    - 识别高频失败查询
    - 发现知识库盲区
    - 优化检索策略
    """
    limit = request.args.get('limit', 20, type=int)

    try:
        feedback_service = _get_feedback_service()

        # 获取低分问题
        bad_cases = feedback_service.get_low_rating_queries(limit=limit)

        # 获取黑名单来源
        blacklisted_sources = feedback_service.get_low_rated_sources(min_count=3)

        # 标记处理状态
        for case in bad_cases:
            case['status'] = 'pending'  # pending/resolved/ignored

        return jsonify({
            "success": True,
            "bad_cases": bad_cases,
            "blacklisted_sources": blacklisted_sources,
            "suggestions": [
                "补充到知识库（针对知识盲区）",
                "添加到 Query Rewrite 规则（针对表达歧义）",
                "标记为知识库盲区（暂不处理）"
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@feedback_bp.route('/feedback/blacklist', methods=['GET'])
@require_gateway_auth
@require_role('admin')
def get_chunk_blacklist():
    """
    获取 Chunk 黑名单（管理员）

    返回被多次点踩的来源，用于在检索时降权或过滤
    """
    min_dislikes = request.args.get('min_dislikes', 3, type=int)

    try:
        feedback_service = _get_feedback_service()
        blacklist = feedback_service.get_chunk_blacklist(min_dislikes=min_dislikes)

        return jsonify({
            "success": True,
            "blacklist": list(blacklist),
            "count": len(blacklist),
            "usage": "在检索时过滤这些来源以提升回答质量"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
