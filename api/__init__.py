"""
API 路由层 — 应用工厂

核心路由:
- chat_routes.py      : /chat, /rag, /rag/stream, /search
- kb_routes.py        : /collections, /documents/sync
- document_routes.py  : /documents/upload, /documents/list, /documents/*, /chunks/*
- sync_routes.py      : /sync, /sync/status
- image_routes.py     : /images/*
- exam_pkg/api.py     : /exam/generate, /exam/grade

注意：
- 会话管理、审计日志、反馈系统由后端负责
- 权限验证由后端网关完成
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
    from flask import Flask, send_from_directory
    from flask_cors import CORS
    from config import ENABLE_SESSION, ENABLE_FEEDBACK, IS_PROD

    # 静态文件目录（前端）
    static_folder = os.path.join(PROJECT_ROOT, 'chat-ui')

    app = Flask(__name__, static_folder=static_folder, static_url_path='')
    CORS(app)

    # ==================== Repository 依赖注入 ====================

    # 会话存储：开发环境用SQLite，生产环境无状态
    if ENABLE_SESSION:
        from repositories.sqlite_session_repo import SQLiteSessionRepo
        app.session_repo = SQLiteSessionRepo()
        print("[INFO] 会话存储: SQLite (开发环境)")
    else:
        from repositories.stateless_session_repo import StatelessSessionRepo
        app.session_repo = StatelessSessionRepo()
        print("[INFO] 会话存储: 无状态 (生产环境)")

    # ==================== 核心服务初始化 ====================

    # Agentic RAG 引擎
    try:
        from core.agentic import AgenticRAG
        from config import ENABLE_WEB_SEARCH, ENABLE_GRAPH_RAG
        agentic_rag = AgenticRAG(
            enable_web_search=ENABLE_WEB_SEARCH,
            enable_graph=ENABLE_GRAPH_RAG
        )
        app.config['AGENTIC_RAG'] = agentic_rag
        print(f"[INFO] Agentic RAG 引擎已初始化（网络搜索={'启用' if ENABLE_WEB_SEARCH else '关闭'}，图谱检索={'启用' if ENABLE_GRAPH_RAG else '关闭'}）")
    except Exception as e:
        app.config['AGENTIC_RAG'] = None
        print(f"[WARN] Agentic RAG 初始化失败: {e}")

    # 同步服务
    try:
        from knowledge.sync import KnowledgeSyncService
        from config import DOCUMENTS_PATH
        sync_service = KnowledgeSyncService(documents_path=DOCUMENTS_PATH)
        app.config['SYNC_SERVICE'] = sync_service
        print("[INFO] 知识库同步服务已初始化")
    except Exception as e:
        app.config['SYNC_SERVICE'] = None
        print(f"[WARN] 知识库同步服务未启用: {e}")

    # 会话管理器（仅开发环境）
    if ENABLE_SESSION:
        try:
            from services.session import SessionManager
            session_manager = SessionManager()
            app.config['SESSION_MANAGER'] = session_manager
            print("[INFO] 会话管理器已初始化")
        except Exception as e:
            app.config['SESSION_MANAGER'] = None
            print(f"[WARN] 会话管理器初始化失败: {e}")

    # ==================== 注册 Blueprint ====================

    # 核心 API
    from api.chat_routes import chat_bp
    from api.kb_routes import kb_bp
    from api.document_routes import document_bp
    from api.sync_routes import sync_bp

    app.register_blueprint(chat_bp)
    app.register_blueprint(kb_bp)
    app.register_blueprint(document_bp)
    app.register_blueprint(sync_bp)

    # 图片服务
    from api.image_routes import image_bp
    app.register_blueprint(image_bp)

    # 健康检查
    from api.auth_routes import auth_bp
    app.register_blueprint(auth_bp)

    # 会话管理（仅开发环境）
    if ENABLE_SESSION:
        try:
            from api.session_routes import session_bp
            app.register_blueprint(session_bp)
            print("[INFO] 会话管理 API 已启用")
        except ImportError as e:
            print(f"[INFO] 会话管理 API 未加载: {e}")

    # 反馈系统（开发和生产环境都启用）
    if ENABLE_FEEDBACK:
        try:
            from api.feedback_routes import feedback_bp
            app.register_blueprint(feedback_bp)
            print("[INFO] 反馈系统 API 已启用")
        except ImportError as e:
            print(f"[INFO] 反馈系统 API 未加载: {e}")

    # 图谱服务（跳过，不使用）
    # try:
    #     from api.graph_routes import graph_bp
    #     app.register_blueprint(graph_bp)
    #     print("✓ 知识图谱 API 已启用")
    # except ImportError as e:
    #     print(f"提示: 知识图谱 API 未加载: {e}")

    # 出题系统（可选）
    try:
        from exam_pkg.api import exam_bp
        app.register_blueprint(exam_bp, url_prefix='/exam')
        print("[INFO] 出题系统 API 已启用: /exam")
    except ImportError as e:
        print(f"[INFO] 出题系统 API 未加载: {e}")

    # ==================== 生产环境启动校验 ====================

    if IS_PROD:
        _validate_production_config()

    # ==================== 前端静态文件路由 ====================

    # 首页
    @app.route('/')
    def serve_index():
        """首页"""
        return send_from_directory(static_folder, 'index.html')

    # 静态文件（需要明确指定，避免与 API 路由冲突）
    @app.route('/app.js')
    def serve_app_js():
        return send_from_directory(static_folder, 'app.js')

    @app.route('/style.css')
    def serve_style_css():
        return send_from_directory(static_folder, 'style.css')

    @app.route('/exam.html')
    def serve_exam_html():
        return send_from_directory(static_folder, 'exam.html')

    @app.route('/exam.js')
    def serve_exam_js():
        return send_from_directory(static_folder, 'exam.js')

    @app.route('/api-test.html')
    def serve_api_test_html():
        return send_from_directory(static_folder, 'api-test.html')

    @app.route('/api-test.js')
    def serve_api_test_js():
        return send_from_directory(static_folder, 'api-test.js')

    # ==================== 启动信息 ====================

    _print_startup_info(app)

    return app


def _validate_production_config():
    """生产环境启动前检查"""
    import os
    from config import DASHSCOPE_API_KEY
    # 检查环境变量或配置文件中的 API Key
    has_key = os.getenv("DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY
    assert has_key and has_key != "", \
        "Missing DASHSCOPE_API_KEY in production environment"
    print("[PROD] Configuration validated")


def _print_startup_info(app):
    """打印启动信息摘要"""
    route_count = len([rule for rule in app.url_map.iter_rules() if rule.endpoint != 'static'])

    print(f"\n[INFO] 应用初始化完成，共注册 {route_count} 个路由")
    print("  问答接口: /chat, /rag, /rag/stream, /search")
    print("  向量库:   /collections, /collections/<name>")
    print("  文档管理: /documents/upload, /documents/list, /documents/*")
    print("  切片管理: /chunks/*")
    print("  同步服务: /sync, /sync/status")
    print("  图片服务: /images/*")
    print("  健康检查: /health")
