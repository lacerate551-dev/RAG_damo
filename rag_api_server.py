"""
⚠️ 此文件已重构为兼容层

所有路由已迁移到 api/ 目录下的 Blueprint 文件。
请使用 python main.py 启动服务。

本文件保留仅为向后兼容：
  - 旧脚本中 `from rag_api_server import app` 仍可工作
  - 直接执行 `python rag_api_server.py` 仍可启动服务

路由文件清单:
  api/chat_routes.py      → /chat, /rag, /search
  api/session_routes.py   → /sessions, /history, /session, /clear
  api/auth_routes.py      → /stats, /health, /auth/me
  api/kb_routes.py        → /collections, /documents/sync, /kb/route
  api/document_routes.py  → /documents/upload, /documents/list, /documents/*
  api/sync_routes.py      → /sync, /sync/status
  api/graph_routes.py     → /graph/search, /graph/stats
  api/question_routes.py  → /questions/*, /exam/*/analyze
  api/outline_routes.py   → /outline/*, /recommend/*
  api/feedback_routes.py  → /feedback/*, /faq/*
  api/image_routes.py     → /images/*
"""

import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import create_app

# 创建应用实例（供 `from rag_api_server import app` 使用）
app = create_app()

if __name__ == '__main__':
    print("=" * 60)
    print("RAG API 服务启动")
    print("⚠️  建议使用 python main.py 启动")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True, use_reloader=False)
