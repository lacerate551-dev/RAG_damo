"""
API 路由层 — 应用工厂

所有路由已拆分为独立 Blueprint 文件:
- chat_routes.py      : /chat, /rag, /rag/stream, /search
- session_routes.py   : /sessions, /history, /session, /clear
- auth_routes.py      : /stats, /health, /auth/me
- audit_routes.py     : /audit/logs
- kb_routes.py        : /collections, /documents/sync, /kb/route
- document_routes.py  : /documents/upload, /documents/list, /documents/*, 版本管理
- sync_routes.py      : /sync, /subscribe, /subscriptions, /notifications
- graph_routes.py     : /graph/search, /graph/build, /graph/stats
- question_routes.py  : /questions/*, /knowledge-points, /exam/*/analyze, /analysis/*
- outline_routes.py   : /outline/*, /recommend/*
- feedback_routes.py  : /feedback/*, /reports/*, /faq/*
"""

import sys
import os

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def create_app():
    """
    应用工厂函数

    创建并配置 Flask 应用，注册所有 Blueprint。
    """
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    # ==================== 共享服务初始化 ====================

    from services.session import SessionManager
    from services.audit import AuditLogger
    from core.agentic import AgenticRAG
    from auth.gateway import get_auth_manager

    session_manager = SessionManager(session_expire_hours=24)
    audit_logger = AuditLogger()
    agentic_rag = AgenticRAG()
    auth_manager = get_auth_manager()

    app.config['SESSION_MANAGER'] = session_manager
    app.config['AUDIT_LOGGER'] = audit_logger
    app.config['AGENTIC_RAG'] = agentic_rag

    # 同步服务（可选）
    try:
        from knowledge.sync import KnowledgeSyncService
        from config import DOCUMENTS_PATH
        sync_service = KnowledgeSyncService(documents_path=DOCUMENTS_PATH)
        app.config['SYNC_SERVICE'] = sync_service
        print("✓ 知识库同步服务已初始化")
    except (ImportError, Exception) as e:
        app.config['SYNC_SERVICE'] = None
        print(f"✗ 知识库同步服务未启用: {e}")

    # ==================== 注册 Blueprint ====================

    # 核心路由（无条件注册）
    from api.auth_routes import auth_bp
    from api.session_routes import session_bp
    from api.audit_routes import audit_bp
    from api.chat_routes import chat_bp
    from api.kb_routes import kb_bp
    from api.document_routes import document_bp
    from api.sync_routes import sync_bp
    from api.graph_routes import graph_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(kb_bp)
    app.register_blueprint(document_bp)
    app.register_blueprint(sync_bp)
    app.register_blueprint(graph_bp)

    # 图片服务
    from api.image_routes import image_bp
    app.register_blueprint(image_bp)

    # 题库维护（可选模块）
    try:
        from api.question_routes import question_bp
        app.register_blueprint(question_bp)
    except ImportError as e:
        print(f"提示: 题库维护 API 未加载: {e}")

    # 纲要生成（可选模块）
    try:
        from api.outline_routes import outline_bp
        app.register_blueprint(outline_bp)
    except ImportError as e:
        print(f"提示: 纲要生成 API 未加载: {e}")

    # 问答质量闭环（可选模块）
    try:
        from api.feedback_routes import feedback_bp
        app.register_blueprint(feedback_bp)
    except ImportError as e:
        print(f"提示: 问答质量闭环 API 未加载: {e}")

    # 出题系统蓝图
    try:
        from exam_pkg.api import exam_bp
        app.register_blueprint(exam_bp, url_prefix='/exam')
        print("✓ 出题系统 API 已启用: /exam")
    except ImportError as e:
        print(f"提示: 出题系统 API 未加载: {e}")

    # ==================== 启动信息 ====================

    _print_startup_info(app)

    return app


def _print_startup_info(app):
    """打印启动信息摘要"""
    # 收集已注册的路由数量
    route_count = len([rule for rule in app.url_map.iter_rules() if rule.endpoint != 'static'])

    print(f"\n✓ 应用初始化完成，共注册 {route_count} 个路由")
    print("  核心路由: /chat, /rag, /rag/stream, /search")
    print("  会话管理: /sessions, /history, /session, /clear")
    print("  系统状态: /health, /stats, /auth/me")
    print("  向量库:   /collections, /documents/sync, /kb/route")
    print("  文档管理: /documents/upload, /documents/list, /documents/*")
    print("  同步通知: /sync/*, /subscribe, /notifications")
    print("  图谱:     /graph/search, /graph/build, /graph/stats")
    print("  图片:     /images/<id>, /images/list, /images/stats")
