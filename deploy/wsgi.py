"""
Gunicorn WSGI 入口文件

用于生产环境部署，通过 Gunicorn 启动 Flask 应用。

使用方式:
    gunicorn -c deploy/gunicorn.conf.py deploy.wsgi:app
"""
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import create_app

# 确保环境变量已设置
os.environ.setdefault('APP_ENV', 'prod')

# 创建应用实例
app = create_app()

if __name__ == "__main__":
    app.run()
