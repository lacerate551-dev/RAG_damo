"""
API 路由层

目前 rag_api_server.py 仍作为主要路由注册文件。
后续阶段将逐步拆分为独立 Blueprint 文件:
- chat_routes.py
- session_routes.py
- kb_routes.py
- sync_routes.py
- graph_routes.py
- outline_routes.py
- feedback_routes.py
- document_routes.py
- question_routes.py
"""


def create_app():
    """
    应用工厂函数

    创建并配置 Flask 应用。
    目前直接复用 rag_api_server 中已有的 app 实例，
    后续重构将逐步改为在此处组装 Blueprint。
    """
    # 暂时直接导入现有的 app
    # rag_api_server.py 中的模块级代码会在 import 时执行初始化
    from rag_api_server import app
    return app
