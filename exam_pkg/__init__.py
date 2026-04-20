"""
考试系统模块

职责边界：
- RAG 服务负责：生成题目 + 批阅答案
- 后端服务负责：审核入库 + 状态管理

包含：
- generator: 出题生成器（本地 LLM 调用）
- grader: 批题器（本地 + LLM 评分）
- manager: 出题与批题核心逻辑
- api: Flask Blueprint API 路由
- local_db: 本地题库数据库（缓存）
"""

from exam_pkg.generator import (
    QuestionGenerator,
    build_semantic_query,
    build_source_context,
    safe_parse_questions,
    validate_questions_schema,
    generate_questions_from_content
)

from exam_pkg.grader import (
    AnswerGrader,
    grade_answers,
    grade_objective,
    grade_fill_blank
)

from exam_pkg.api import exam_bp

__all__ = [
    # 生成器
    'QuestionGenerator',
    'build_semantic_query',
    'build_source_context',
    'safe_parse_questions',
    'validate_questions_schema',
    'generate_questions_from_content',

    # 批题器
    'AnswerGrader',
    'grade_answers',
    'grade_objective',
    'grade_fill_blank',

    # API
    'exam_bp'
]
