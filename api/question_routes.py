"""
题库维护 + 整卷分析 API

路由:
- POST /questions/link-document              - 建立题目-制度关联
- POST /questions/link-knowledge             - 建立题目-知识点关联
- GET  /questions/affected                   - 获取受影响题目
- POST /questions/<question_id>/review       - 审核受影响题目
- GET  /documents/<document_id>/questions    - 获取制度关联题目
- GET  /documents/<document_id>/versions     - 获取制度版本历史
- GET  /knowledge-points                     - 获取知识点列表
- GET  /questions/suggestions                - 获取新题建议
- POST /exam/<exam_id>/analyze               - 整卷分析
- GET  /analysis/<report_id>                 - 获取分析报告
- GET  /analysis/list                        - 分析报告列表
- GET  /questions/<question_id>/knowledge-points - 获取题目知识点
"""

from dataclasses import asdict
from flask import Blueprint, request, jsonify
from auth.gateway import require_gateway_auth

question_bp = Blueprint('question', __name__)

# 延迟初始化
_exam_checked = False
_has_exam_analysis = False
_exam_analysis_db = None
_maintenance_service = None
_analysis_service = None


def _check_exam_analysis():
    global _exam_checked, _has_exam_analysis, _exam_analysis_db, _maintenance_service, _analysis_service
    if not _exam_checked:
        try:
            from exam_pkg.analysis import ExamAnalysisDB, QuestionMaintenanceService, ExamAnalysisService
            _exam_analysis_db = ExamAnalysisDB("./data/exam_analysis.db")
            _maintenance_service = QuestionMaintenanceService(_exam_analysis_db)
            _analysis_service = ExamAnalysisService(_exam_analysis_db)
            _has_exam_analysis = True
        except ImportError as e:
            print(f"警告: 题库分析模块导入失败: {e}")
            _has_exam_analysis = False
        _exam_checked = True
    return _has_exam_analysis


def _require_exam_analysis():
    if not _check_exam_analysis():
        return None, None, None, (jsonify({"error": "题库分析模块未启用"}), 503)
    return _exam_analysis_db, _maintenance_service, _analysis_service, None


@question_bp.route('/questions/link-document', methods=['POST'])
@require_gateway_auth
def link_question_to_document():
    """建立题目-制度关联"""
    _, maintenance_service, _, err = _require_exam_analysis()
    if err:
        return err

    data = request.get_json()

    question_id = data.get('question_id')
    question_type = data.get('question_type')
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


@question_bp.route('/questions/link-knowledge', methods=['POST'])
@require_gateway_auth
def link_question_to_knowledge():
    """建立题目-知识点关联"""
    _, maintenance_service, _, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/questions/affected', methods=['GET'])
@require_gateway_auth
def get_affected_questions():
    """获取受影响的题目列表"""
    _, maintenance_service, _, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/questions/<question_id>/review', methods=['POST'])
@require_gateway_auth
def review_affected_question(question_id):
    """审核受影响的题目"""
    _, maintenance_service, _, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/documents/<document_id>/questions', methods=['GET'])
@require_gateway_auth
def get_document_questions(document_id):
    """获取制度文档关联的题目"""
    exam_analysis_db, _, _, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/documents/<document_id>/versions', methods=['GET'])
@require_gateway_auth
def get_document_versions(document_id):
    """获取制度版本历史"""
    exam_analysis_db, _, _, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/knowledge-points', methods=['GET'])
@require_gateway_auth
def get_knowledge_points():
    """获取知识点列表"""
    exam_analysis_db, _, _, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/questions/suggestions', methods=['GET'])
@require_gateway_auth
def get_question_suggestions():
    """获取新题建议"""
    exam_analysis_db, _, _, err = _require_exam_analysis()
    if err:
        return err

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


# ==================== 整卷分析 ====================

@question_bp.route('/exam/<exam_id>/analyze', methods=['POST'])
@require_gateway_auth
def analyze_exam_paper(exam_id):
    """整卷分析"""
    _, _, analysis_service, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/analysis/<report_id>', methods=['GET'])
@require_gateway_auth
def get_analysis_report(report_id):
    """获取分析报告"""
    _, _, analysis_service, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/analysis/list', methods=['GET'])
@require_gateway_auth
def list_analysis_reports():
    """获取分析报告列表"""
    _, _, analysis_service, err = _require_exam_analysis()
    if err:
        return err

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


@question_bp.route('/questions/<question_id>/knowledge-points', methods=['GET'])
@require_gateway_auth
def get_question_knowledge_points(question_id):
    """获取题目关联的知识点"""
    exam_analysis_db, _, _, err = _require_exam_analysis()
    if err:
        return err

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
