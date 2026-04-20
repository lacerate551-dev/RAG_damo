"""
出题与批题系统 API 蓝图

提供 REST API 接口：
- 出题：生成题目（返回 JSON 给后端）
- 批题：批阅答案（返回结果给后端）

职责边界：
- RAG 服务负责：生成题目 + 批阅答案
- 后端服务负责：审核入库 + 状态管理

使用方式：
    from exam_pkg.api import exam_bp
    app.register_blueprint(exam_bp, url_prefix='/exam')
"""

from flask import Blueprint, request, jsonify
import os

# 导入考试管理模块
from exam_pkg.manager import (
    generate_questions_from_file,
    grade_answers,
)

# 导入网关认证模块
from auth.gateway import (
    require_gateway_auth, require_role, check_collection_permission, get_current_user
)

# 创建蓝图
exam_bp = Blueprint('exam', __name__)


# ==================== 出题 API ====================

@exam_bp.route('/generate', methods=['POST'])
@require_gateway_auth
def api_generate_questions():
    """
    🔥 新版出题接口

    请求体:
    {
        "request_id": "uuid-optional",  // 幂等性支持
        "file_path": "public/产品手册.pdf",
        "collection": "public_kb",
        "question_types": {
            "single_choice": 3,
            "multiple_choice": 2,
            "true_false": 2,
            "fill_blank": 2,
            "subjective": 1
        },
        "difficulty": 3,
        "options": {
            "include_explanation": true,
            "max_source_chunks": 50
        }
    }

    返回:
    {
        "success": true,
        "request_id": "uuid",
        "questions": [
            {
                "metadata": {"question_id": "...", "question_type": "...", ...},
                "source_trace": {"document_name": "...", "sources": [...], ...},
                "content": {"stem": "...", "data": {...}, "answer": "...", ...}
            }
        ],
        "total": 10,
        "source_chunks_used": 15
    }
    """
    try:
        data = request.json

        file_path = data.get('file_path')
        collection = data.get('collection')
        question_types = data.get('question_types', {})

        if not file_path or not collection:
            return jsonify({"error": "缺少 file_path 或 collection 参数"}), 400

        if not question_types:
            return jsonify({"error": "缺少 question_types 参数"}), 400

        # 获取当前用户
        user = get_current_user()
        if not user:
            return jsonify({"error": "未认证"}), 401

        # 检查向量库访问权限
        if not check_collection_permission(
            role=user['role'],
            department=user.get('department', ''),
            collection_name=collection,
            operation="read"
        ):
            return jsonify({
                "error": "权限不足",
                "message": f"您没有权限访问向量库 '{collection}'"
            }), 403

        # 调用新版出题接口
        result = generate_questions_from_file(
            file_path=file_path,
            collection=collection,
            question_types=question_types,
            difficulty=data.get('difficulty', 3),
            options=data.get('options', {}),
            request_id=data.get('request_id')
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 批题 API ====================

@exam_bp.route('/grade', methods=['POST'])
@require_gateway_auth
def api_grade_answers():
    """
    🔥 新版批题接口

    请求体:
    {
        "request_id": "uuid-optional",
        "answers": [
            {
                "question_id": "uuid",
                "question_type": "single_choice",
                "question_content": {"answer": "B"},
                "student_answer": "A",
                "max_score": 2
            },
            {
                "question_id": "uuid",
                "question_type": "fill_blank",
                "question_content": {"answer": [["答案1"], ["答案2"]]},
                "student_answer": ["学生答案1", "学生答案2"],
                "max_score": 4
            },
            {
                "question_id": "uuid",
                "question_type": "subjective",
                "question_content": {
                    "stem": "简述...",
                    "data": {"scoring_points": [...]},
                    "answer": "参考范文..."
                },
                "student_answer": "学生作答内容...",
                "max_score": 10
            }
        ]
    }

    返回:
    {
        "success": true,
        "request_id": "uuid",
        "results": [...],
        "total_score": 10.5,
        "total_max_score": 16.0,
        "score_rate": 65.6
    }
    """
    try:
        data = request.json

        answers = data.get('answers', [])
        if not answers:
            return jsonify({"error": "缺少答案数据"}), 400

        # 调用新版批题接口
        result = grade_answers(
            answers=answers,
            request_id=data.get('request_id')
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
        "service": "exam-api",
        "version": "2.0"
    })
