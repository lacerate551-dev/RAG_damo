"""
RAG API 服务 - 统一启动入口

使用方式:
    python main.py                    # 启动服务（默认端口 5001）
    python main.py --port 8080        # 指定端口
    python main.py --host 127.0.0.1   # 仅本机访问

等效于旧入口: python rag_api_server.py
"""

import sys
import os
import argparse

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(description='RAG API 服务')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址（默认 0.0.0.0）')
    parser.add_argument('--port', type=int, default=5001, help='监听端口（默认 5001）')
    parser.add_argument('--debug', action='store_true', default=True, help='调试模式')
    parser.add_argument('--no-debug', action='store_true', help='关闭调试模式')
    args = parser.parse_args()

    debug = args.debug and not args.no_debug

    # 通过工厂函数创建应用
    from api import create_app
    app = create_app()

    print(f"\n🚀 RAG API 服务启动: http://{args.host}:{args.port}")
    print(f"   调试模式: {'开启' if debug else '关闭'}")

    app.run(
        host=args.host,
        port=args.port,
        debug=debug,
        threaded=True,
        use_reloader=False
    )


if __name__ == '__main__':
    main()
