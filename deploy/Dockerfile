# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 使用阿里云镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python依赖（使用阿里云 pip 镜像）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    && pip install gunicorn>=21.0.0 \
    -i https://mirrors.aliyun.com/pypi/simple/

# 应用代码
COPY . .

# 创建 MinerU 配置文件（生产环境）
RUN echo '{\n\
  "models-dir": {\n\
    "pipeline": "/app/models/mineru/pipeline",\n\
    "vlm": "/app/models/mineru/vlm"\n\
  },\n\
  "config_version": "1.3.1"\n\
}' > /root/mineru.json

# 设置 MinerU 环境变量
ENV MINERU_MODEL_SOURCE=local
ENV MINERU_TOOLS_CONFIG_JSON=/root/mineru.json

# 创建数据目录（生产环境可能不需要，但保留以防万一）
RUN mkdir -p data knowledge/vector_store .data documents models

EXPOSE 5001

# 生产模式启动（使用配置文件）
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "deploy.wsgi:app"]
