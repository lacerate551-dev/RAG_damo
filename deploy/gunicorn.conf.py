# gunicorn.conf.py - Gunicorn生产配置

import multiprocessing
import os

# 服务器绑定
bind = "0.0.0.0:5001"

# Worker配置
# 单 worker 模式，适合资源有限环境
workers = int(os.getenv("GUNICORN_WORKERS", 1))
worker_class = "gthread"  # 线程worker，可发送心跳（原 sync）
threads = 2  # 每个worker 2个线程
worker_connections = 1000
max_requests = 1000  # 每个worker处理1000个请求后重启（防止内存泄漏）
max_requests_jitter = 50

# 超时配置
timeout = 120  # 优化后不应超过2分钟（原 300）
graceful_timeout = 60
keepalive = 5

# 日志配置
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 进程命名
proc_name = "rag-service"

# 预加载应用（gthread 模式下必须关闭，否则 fork 后线程资源死锁）
preload_app = False

# 守护进程（Docker中不需要）
daemon = False

# 临时文件目录
worker_tmp_dir = "/dev/shm"  # 使用内存文件系统，提升性能

# 钩子函数
def on_starting(server):
    """服务启动时"""
    print(f"[INFO] Starting Gunicorn with {workers} workers")

def on_reload(server):
    """重载时"""
    print("[INFO] Reloading Gunicorn")

def worker_int(worker):
    """Worker被中断时"""
    print(f"[INFO] Worker {worker.pid} interrupted")

def worker_abort(worker):
    """Worker异常退出时"""
    print(f"[ERROR] Worker {worker.pid} aborted")
