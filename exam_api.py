"""
出题与批卷系统 API 蓝图

提供 REST API 接口：
- 出题：生成试卷、保存、审核
- 批卷：提交答案、批阅、报告

使用方式：
    from exam_api import exam_bp
    app.register_blueprint(exam_bp, url_prefix='/exam')
"""

from flask import Blueprint, request, jsonify
from functools import wraps
import jwt
import os

# 导入考试管理模块
from exam_manager import (
    generate_exam, save_exam, load_exam, delete_exam,
    list_exams, get_exam_by_id, update_exam,
    review_exam, submit_for_review, search_questions,
    grade_exam, save_grade_report, get_report_by_id, list_reports,
    generate_exam_by_file, grade_from_mysql,
    EXAM_STATUS_DRAFT, EXAM_STATUS_PENDING, EXAM_STATUS_APPROVED, EXAM_STATUS_REJECTED
)

# 导入网关认证模块
from auth_gateway import (
    require_gateway_auth, check_collection_permission, get_current_user
)

# 创建蓝图
exam_bp = Blueprint('exam', __name__)

# JWT 配置（保留用于其他功能，但不再覆盖 get_current_user）
# 密钥长度至少32字节以满足SHA256要求
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-change-in-production-32b!')


# ==================== 认证装饰器 ====================
# 注意: get_current_user 已从 auth_gateway 导入，无需重复定义

def require_auth(f):
    """要求登录（网关认证）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '缺少认证信息，请通过网关访问'}), 401
        # 将用户信息附加到请求上下文
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """要求管理员权限"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '缺少认证信息，请通过网关访问'}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': '需要管理员权限'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


# ==================== 出题相关 API ====================

@exam_bp.route('/generate-by-file', methods=['POST'])
@require_gateway_auth
def api_generate_exam_by_file():
    """
    按文件生成题目

    请求体:
    {
        "file_path": "public/产品手册.pdf",
        "collection": "public_kb",
        "choice_count": 5,
        "blank_count": 2,
        "short_answer_count": 2,
        "difficulty": 3,
        "choice_score": 2,
        "blank_score": 3
    }

    返回:
    {
        "source_file": {"path": "...", "collection": "..."},
        "choice_questions": [...],
        "blank_questions": [...],
        "short_answer_questions": [...],
        "total_count": 9,
        "total_score": 22
    }
    """
    try:
        data = request.json

        file_path = data.get('file_path')
        collection = data.get('collection')

        if not file_path or not collection:
            return jsonify({"error": "缺少 file_path 或 collection 参数"}), 400

        # 获取当前用户
        user = get_current_user()
        print(f"[DEBUG] get_current_user() = {user}")  # 调试日志
        print(f"[DEBUG] request.current_user = {getattr(request, 'current_user', 'NOT SET')}")  # 调试日志
        print(f"[DEBUG] X-User-ID header = {request.headers.get('X-User-ID')}")  # 调试日志
        if not user:
            return jsonify({"error": "未认证", "debug": "current_user is None"}), 401

        # 检查向量库访问权限
        if not check_collection_permission(
            role=user['role'],
            department=user.get('department', ''),
            collection_name=collection,
            operation="read"
        ):
            return jsonify({
                "error": "权限不足",
                "message": f"您没有权限访问向量库 '{collection}'",
                "your_role": user['role'],
                "your_department": user.get('department', ''),
                "target_collection": collection
            }), 403

        # 按文件生成题目（传入用户信息用于工作流认证）
        result = generate_exam_by_file(
            file_path=file_path,
            collection=collection,
            user_id=user.get('user_id'),
            user_role=user.get('role'),
            user_department=user.get('department'),
            choice_count=data.get('choice_count', 3),
            blank_count=data.get('blank_count', 2),
            short_answer_count=data.get('short_answer_count', 2),
            difficulty=data.get('difficulty', 3),
            choice_score=data.get('choice_score', 2),
            blank_score=data.get('blank_score', 3),
            created_by=data.get('created_by'),
            name=data.get('name')
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/generate', methods=['POST'])
@require_auth
def api_generate_exam():
    """
    生成试卷

    请求体:
    {
        "topic": "Python基础知识",
        "choice_count": 5,
        "blank_count": 3,
        "short_answer_count": 2,
        "difficulty": 2,
        "choice_score": 2,
        "blank_score": 3
    }

    返回:
    {
        "exam_id": "uuid",
        "status": "draft",
        "choice_questions": [...],
        "blank_questions": [...],
        "short_answer_questions": [...],
        "total_count": 10,
        "total_score": 25
    }
    """
    try:
        data = request.json

        topic = data.get('topic', '')
        if not topic:
            return jsonify({"error": "缺少主题参数"}), 400

        # 生成试卷
        exam = generate_exam(
            topic=topic,
            choice_count=data.get('choice_count', 3),
            blank_count=data.get('blank_count', 2),
            short_answer_count=data.get('short_answer_count', 2),
            difficulty=data.get('difficulty', 3),
            choice_score=data.get('choice_score', 2),
            blank_score=data.get('blank_score', 3),
            created_by=data.get('created_by'),
            name=data.get('name')  # 试卷名称
        )

        # 自动保存草稿
        save_exam(exam)

        return jsonify(exam)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/list', methods=['GET'])
@require_auth
def api_list_exams():
    """
    获取试卷列表

    参数:
        status: 状态过滤 (draft/pending_review/approved/rejected)
        page: 页码 (默认1)
        limit: 每页数量 (默认20)

    返回:
    {
        "exams": [...],
        "total": 5,
        "page": 1
    }
    """
    try:
        status = request.args.get('status')
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))

        result = list_exams(status=status, page=page, limit=limit)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/<exam_id>', methods=['GET'])
@require_auth
def api_get_exam(exam_id):
    """
    获取试卷详情

    返回:
    {
        "exam_id": "uuid",
        "status": "draft",
        "choice_questions": [...],
        ...
    }
    """
    try:
        exam = get_exam_by_id(exam_id)
        if not exam:
            return jsonify({"error": "试卷不存在"}), 404

        return jsonify(exam)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/<exam_id>', methods=['PUT'])
@require_auth
def api_update_exam(exam_id):
    """
    更新试卷

    请求体:
    {
        "choice_questions": [...],
        "blank_questions": [...],
        ...
    }
    """
    try:
        data = request.json

        exam = update_exam(exam_id, data)
        if not exam:
            return jsonify({"error": "试卷不存在"}), 404

        return jsonify(exam)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/<exam_id>', methods=['DELETE'])
@require_auth
def api_delete_exam(exam_id):
    """删除试卷"""
    try:
        success = delete_exam(exam_id)
        if not success:
            return jsonify({"error": "试卷不存在"}), 404

        return jsonify({"success": True, "message": "试卷已删除"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/<exam_id>/submit', methods=['POST'])
@require_auth
def api_submit_exam(exam_id):
    """
    提交试卷审核

    返回:
    {
        "success": true,
        "status": "pending_review"
    }
    """
    try:
        result = submit_for_review(exam_id)
        if not result.get("success"):
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/<exam_id>/review', methods=['POST'])
@require_admin
def api_review_exam(exam_id):
    """
    审核试卷

    整体审核:
    {
        "action": "approve" | "reject",
        "feedback": "审核意见（可选）"
    }

    逐题审核:
    {
        "action": "partial",
        "questions": [
            {"type": "choice", "id": 1, "approved": true},
            {"type": "choice", "id": 2, "approved": false, "edit": {"content": "修改后..."}},
            {"type": "blank", "id": 1, "delete": true}
        ]
    }
    """
    try:
        data = request.json
        action = data.get('action')

        if action not in ['approve', 'reject', 'partial']:
            return jsonify({"error": "无效的审核动作"}), 400

        result = review_exam(
            exam_id=exam_id,
            action=action,
            questions=data.get('questions'),
            feedback=data.get('feedback')
        )

        if not result.get("success"):
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 批卷相关 API ====================

@exam_bp.route('/grade-from-mysql', methods=['POST'])
@require_auth
def api_grade_from_mysql():
    """
    基于前端传入的题目批卷

    请求体:
    {
        "exam_id": "试卷ID",
        "student_id": "学生ID",
        "student_name": "张三",
        "answers": [
            {
                "question_id": "q_uuid_001",
                "question_type": "choice",
                "question_content": "题目内容",
                "correct_answer": "A",
                "max_score": 2,
                "student_answer": "B"
            },
            {
                "question_id": "q_uuid_002",
                "question_type": "blank",
                "question_content": "填空题内容______",
                "correct_answer": "正确答案",
                "max_score": 3,
                "student_answer": "学生答案"
            },
            {
                "question_id": "q_uuid_003",
                "question_type": "short_answer",
                "question_content": "简答题内容",
                "correct_answer": "{\"points\":[{\"point\":\"要点1\",\"score\":3}]}",
                "max_score": 10,
                "student_answer": "学生作答内容..."
            }
        ]
    }

    返回:
    {
        "report_id": "uuid",
        "exam_id": "试卷ID",
        "student_id": "学生ID",
        "student_name": "张三",
        "total_score": 75,
        "max_score": 100,
        "score_rate": 75.0,
        "results": [...]
    }
    """
    try:
        data = request.json

        answers = data.get('answers', [])
        if not answers:
            return jsonify({"error": "缺少答案数据"}), 400

        # 从请求头获取 Authorization token
        auth_header = request.headers.get('Authorization', '')
        user_token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

        # 调用批卷函数
        result = grade_from_mysql(
            exam_id=data.get('exam_id', ''),
            student_id=data.get('student_id', ''),
            student_name=data.get('student_name', '匿名'),
            answers=answers,
            user_token=user_token
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/<exam_id>/grade', methods=['POST'])
@require_auth
def api_grade_exam(exam_id):
    """
    批阅试卷

    请求体:
    {
        "student_name": "张三",
        "answers": {
            "choice_1": "A",
            "choice_2": "B",
            "blank_1": "答案内容",
            "short_answer_1": "简答题作答..."
        }
    }

    返回:
    {
        "report_id": "uuid",
        "student_name": "张三",
        "total_score": 15,
        "max_score": 25,
        "score_rate": 60.0,
        "questions": [...]
    }
    """
    try:
        data = request.json
        student_name = data.get('student_name', '匿名')
        answers = data.get('answers', {})

        if not answers:
            return jsonify({"error": "缺少答案"}), 400

        # 获取试卷
        exam = get_exam_by_id(exam_id)
        if not exam:
            return jsonify({"error": "试卷不存在"}), 404

        # 检查试卷状态
        if exam.get('status') != EXAM_STATUS_APPROVED:
            return jsonify({"error": "试卷未通过审核，不能用于考试"}), 400

        # 批阅
        report = grade_exam(exam_id, answers, student_name)

        # 保存报告
        save_grade_report(report, student_name)

        return jsonify(report)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/report/<report_id>', methods=['GET'])
@require_auth
def api_get_report(report_id):
    """
    获取批阅报告

    返回完整的批阅报告
    """
    try:
        report = get_report_by_id(report_id)
        if not report:
            return jsonify({"error": "报告不存在"}), 404

        return jsonify(report)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@exam_bp.route('/report/list', methods=['GET'])
@require_auth
def api_list_reports():
    """
    获取批阅报告列表

    参数:
        page: 页码 (默认1)
        limit: 每页数量 (默认20)

    返回:
    {
        "reports": [...],
        "total": 10,
        "page": 1
    }
    """
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))

        result = list_reports(page=page, limit=limit)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 题库搜索 API ====================

@exam_bp.route('/questions/search', methods=['GET'])
@require_auth
def api_search_questions():
    """
    搜索题目

    参数:
        keyword: 搜索关键词
        type: 题型过滤 (choice/blank/short_answer)
        difficulty: 难度过滤 (1-5)
        limit: 返回数量 (默认50)

    返回:
    {
        "questions": [...],
        "total": 15
    }
    """
    try:
        keyword = request.args.get('keyword', '')
        question_type = request.args.get('type')
        difficulty = request.args.get('difficulty')
        limit = int(request.args.get('limit', 50))

        if difficulty:
            difficulty = int(difficulty)

        result = search_questions(
            keyword=keyword,
            question_type=question_type,
            difficulty=difficulty,
            limit=limit
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 健康检查 ====================

@exam_bp.route('/health', methods=['GET'])
def api_health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "service": "exam-api"
    })
