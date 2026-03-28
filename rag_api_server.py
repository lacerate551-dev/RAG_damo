"""
带会话管理的 RAG API 服务 - 使用 Agentic RAG

提供 REST API 接口供前端调用：
1. POST /chat - 发送消息并获取回复（普通聊天，直接LLM回复）
2. POST /rag - 发送消息并获取回复（知识库问答，使用Agentic RAG）
3. GET /sessions - 获取用户会话列表
4. DELETE /session/<session_id> - 删除会话
5. GET /history/<session_id> - 获取会话历史

特性：
- 双模式：普通聊天 / 知识库问答
- 多轮对话：记住上下文
- 用户隔离：不同用户会话独立
- 并发支持：多用户同时请求

使用方式：
    python rag_api_server.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session_manager import SessionManager
from agentic_rag import AgenticRAG
from rag_demo import collection, API_KEY, BASE_URL, MODEL
from openai import OpenAI

# 初始化
app = Flask(__name__)
CORS(app)

# 会话管理器
session_manager = SessionManager(db_path="./sessions.db", session_expire_hours=24)

# Agentic RAG 实例（用于知识库问答）
agentic_rag = AgenticRAG()

# LLM 客户端（用于普通聊天，使用更快的模型）
llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
CHAT_MODEL = "qwen3.5-flash"  # 聊天使用更快的模型


def chat_with_llm(message: str, history: list = None) -> str:
    """普通聊天，直接使用LLM回复"""
    messages = [
        {"role": "system", "content": "你是一个友好、专业的智能助手。回答简洁，不超过150字。"}
    ]

    if history:
        for msg in history[-6:]:  # 最近3轮
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    messages.append({"role": "user", "content": message})

    response = llm_client.chat.completions.create(
        model=CHAT_MODEL,  # 使用更快的模型
        messages=messages,
        temperature=0.8,
        max_tokens=300
    )
    return response.choices[0].message.content.strip()


@app.route('/chat', methods=['POST'])
def chat():
    """
    普通聊天模式 - 直接使用LLM回复，速度快

    请求体:
    {
        "user_id": "用户ID",
        "session_id": "会话ID（首次为null）",
        "message": "消息内容"
    }

    返回:
    {
        "session_id": "会话ID",
        "answer": "回复内容",
        "mode": "chat"
    }
    """
    data = request.json

    user_id = data.get('user_id')
    session_id = data.get('session_id')
    message = data.get('message')

    if not user_id or not message:
        return jsonify({"error": "缺少 user_id 或 message"}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 直接LLM回复
    answer = chat_with_llm(message, history)

    # 保存助手回复
    session_manager.add_message(session_id, "assistant", answer)

    return jsonify({
        "session_id": session_id,
        "answer": answer,
        "mode": "chat"
    })


@app.route('/rag', methods=['POST'])
def rag():
    """
    知识库问答模式 - 使用Agentic RAG检索回复

    请求体:
    {
        "user_id": "用户ID",
        "session_id": "会话ID（首次为null）",
        "message": "消息内容"
    }

    返回:
    {
        "session_id": "会话ID",
        "answer": "回复内容",
        "mode": "rag",
        "sources": [{"source": "文件名", "snippet": "..."}]
    }
    """
    data = request.json

    user_id = data.get('user_id')
    session_id = data.get('session_id')
    message = data.get('message')

    if not user_id or not message:
        return jsonify({"error": "缺少 user_id 或 message"}), 400

    # 获取或创建会话
    session_id = session_manager.get_or_create_session(user_id, session_id)

    # 保存用户消息
    session_manager.add_message(session_id, "user", message)

    # 获取历史上下文
    history = session_manager.get_history(session_id, limit=10)

    # 使用 Agentic RAG 处理
    result = agentic_rag.process(message, verbose=False, history=history)

    # 保存助手回复
    session_manager.add_message(session_id, "assistant", result["answer"])

    return jsonify({
        "session_id": session_id,
        "answer": result["answer"],
        "mode": "rag",
        "sources": result.get("sources", [])
    })


@app.route('/sessions', methods=['GET'])
def get_sessions():
    """
    获取用户的会话列表

    参数:
        user_id: 用户ID

    返回:
    {
        "sessions": [
            {
                "session_id": "...",
                "created_at": "...",
                "last_active": "...",
                "preview": "最后一条消息预览..."
            }
        ]
    }
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    sessions = session_manager.get_user_sessions(user_id, limit=20)

    # 添加最后一条消息预览
    for s in sessions:
        history = session_manager.get_history(s["session_id"], limit=1)
        if history:
            s["preview"] = history[0]["content"][:50] + "..."
        else:
            s["preview"] = "空会话"

    return jsonify({"sessions": sessions})


@app.route('/history/<session_id>', methods=['GET'])
def get_history(session_id):
    """
    获取会话历史

    参数:
        user_id: 用户ID（用于验证权限）

    返回:
    {
        "history": [
            {"role": "user/assistant", "content": "...", "created_at": "..."}
        ]
    }
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权访问此会话"}), 403

    history = session_manager.get_history(session_id, limit=100)

    return jsonify({"history": history})


@app.route('/session/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """
    删除会话

    参数:
        user_id: 用户ID（用于验证权限）
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权删除此会话"}), 403

    session_manager.delete_session(session_id)

    return jsonify({"success": True, "message": "会话已删除"})


@app.route('/clear/<session_id>', methods=['POST'])
def clear_history(session_id):
    """
    清空会话历史（保留会话）

    参数:
        user_id: 用户ID（用于验证权限）
    """
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400

    # 验证会话归属
    sessions = session_manager.get_user_sessions(user_id)
    session_ids = [s["session_id"] for s in sessions]

    if session_id not in session_ids:
        return jsonify({"error": "无权操作此会话"}), 403

    session_manager.clear_history(session_id)

    return jsonify({"success": True, "message": "历史已清空"})


@app.route('/stats', methods=['GET'])
def get_stats():
    """获取系统统计信息"""
    return jsonify(session_manager.get_stats())


@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "knowledge_base": f"{collection.count()} 条记录",
        "mode": "Agentic RAG"
    })


if __name__ == '__main__':
    print("=" * 50)
    print("RAG API 服务启动")
    print("=" * 50)
    print(f"知识库: {collection.count()} 条记录")
    print(f"会话数据库: ./sessions.db")
    print()
    print("双模式:")
    print(f"  /chat - 普通聊天模式 (模型: {CHAT_MODEL})")
    print(f"  /rag  - 知识库问答模式 (模型: {MODEL})")
    print()
    print("API 接口:")
    print("  POST /chat          - 普通聊天")
    print("  POST /rag           - 知识库问答")
    print("  GET  /sessions      - 获取会话列表")
    print("  GET  /history/<id>  - 获取会话历史")
    print("  DELETE /session/<id> - 删除会话")
    print("  POST /clear/<id>    - 清空历史")
    print("  GET  /stats         - 统计信息")
    print("  GET  /health        - 健康检查")
    print("=" * 50)

    # threaded=True 支持多用户同时请求
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
