# 部署文件说明

本目录包含所有部署相关的配置文件。

---

## 📁 文件清单

### Docker 部署

| 文件 | 说明 |
|------|------|
| `Dockerfile` | Docker 镜像构建文件 |
| `docker-compose.yml` | Docker Compose 编排配置 |
| `.dockerignore` | Docker 构建忽略文件 |
| `.env.production` | 生产环境变量配置 |

### Web 服务器

| 文件 | 说明 |
|------|------|
| `gunicorn.conf.py` | Gunicorn WSGI 服务器配置 |
| `wsgi.py` | WSGI 应用入口 |
| `nginx.conf` | Nginx 反向代理配置（可选） |

---

## 🚀 快速部署

### 方式 1：Docker Compose（推荐）

```bash
# 1. 构建并启动
docker-compose up -d

# 2. 查看日志
docker-compose logs -f

# 3. 停止服务
docker-compose down
```

### 方式 2：Docker 手动部署

```bash
# 1. 构建镜像
docker build -f deploy/Dockerfile -t rag-service:latest .

# 2. 运行容器
docker run -d \
  -p 5001:5001 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/documents:/app/documents \
  -v $(pwd)/knowledge:/app/knowledge \
  --name rag-service \
  rag-service:latest

# 3. 查看日志
docker logs -f rag-service
```

### 方式 3：直接部署（服务器）

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install gunicorn

# 2. 启动服务
gunicorn -c deploy/gunicorn.conf.py deploy.wsgi:app
```

---

## ⚙️ 配置说明

### Dockerfile

**关键配置**：
- 基础镜像：`python:3.10-slim`
- 工作目录：`/app`
- 暴露端口：`5001`
- 启动命令：`gunicorn -c deploy/gunicorn.conf.py deploy.wsgi:app`

**环境变量**：
```dockerfile
ENV MINERU_MODEL_SOURCE=local
ENV MINERU_TOOLS_CONFIG_JSON=/root/mineru.json
ENV APP_ENV=prod
ENV ENABLE_SESSION=false
```

### docker-compose.yml

**服务配置**：
- 端口映射：`5001:5001`
- 数据卷挂载：`./data`, `./documents`, `./knowledge`
- 自动重启：`unless-stopped`

### gunicorn.conf.py

**性能配置**：
- Workers：`CPU核心数 × 2 + 1`
- Worker类型：`sync`（同步）
- 超时时间：`120秒`
- 最大请求数：`1000`（防止内存泄漏）

### nginx.conf

**反向代理配置**（可选）：
- 负载均衡：`least_conn`
- 请求限流：`10r/s`
- 超时配置：`120s`
- SSE 流式支持：已启用

---

## 🔧 环境变量

### 必需变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `APP_ENV` | 环境标识 | `prod` |
| `MINERU_MODEL_SOURCE` | 模型来源 | `local` |
| `DASHSCOPE_API_KEY` | 通义千问 API Key | 无 |

### 可选变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ENABLE_SESSION` | 会话管理 | `false` |
| `ENABLE_FEEDBACK` | 反馈系统 | `true` |
| `GUNICORN_WORKERS` | Worker 数量 | 自动计算 |

---

## 📊 资源要求

### 最小配置

- CPU：2 核
- 内存：4 GB
- 磁盘：20 GB（含模型）

### 推荐配置

- CPU：4 核
- 内存：8 GB
- 磁盘：50 GB

---

## 🔍 健康检查

### Docker 健康检查

```bash
# 检查容器状态
docker ps

# 检查健康状态
curl http://localhost:5001/health
```

### 服务端点

| 端点 | 说明 |
|------|------|
| `/health` | 健康检查 |
| `/stats` | 服务统计 |
| `/rag` | RAG 问答（SSE 流式） |

---

## 🐛 故障排查

### 容器无法启动

```bash
# 查看日志
docker logs rag-service

# 检查配置
docker exec rag-service cat /root/mineru.json

# 检查模型
docker exec rag-service ls /app/models/mineru
```

### 性能问题

```bash
# 查看资源使用
docker stats rag-service

# 调整 Worker 数量
# 修改 docker-compose.yml 中的 GUNICORN_WORKERS
```

### 端口冲突

```bash
# 修改端口映射
# docker-compose.yml: "5002:5001"
```

---

## 📚 相关文档

- [部署指南](../docs/MinerU模型部署指南.md)
- [配置说明](../docs/后端对接规范.md)
- [故障排查](../docs/绝对路径修复总结.md)

---

**最后更新**: 2026-04-20  
**维护者**: RAG 服务开发组
