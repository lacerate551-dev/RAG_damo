#!/bin/bash
# RAG 服务启动脚本
# 确保在项目根目录运行，并设置正确的环境变量

# 获取脚本所在目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "RAG 服务启动脚本"
echo "========================================="
echo "项目目录: $SCRIPT_DIR"
echo ""

# 设置 MinerU 环境变量
export MINERU_MODEL_SOURCE=local
export MINERU_TOOLS_CONFIG_JSON=mineru.json

echo "环境变量设置："
echo "  MINERU_MODEL_SOURCE=$MINERU_MODEL_SOURCE"
echo "  MINERU_TOOLS_CONFIG_JSON=$MINERU_TOOLS_CONFIG_JSON"
echo ""

# 检查配置文件
if [ ! -f "mineru.json" ]; then
    echo "❌ 错误：mineru.json 配置文件不存在"
    echo "请运行: cp mineru.json.template mineru.json"
    exit 1
fi

echo "✅ 配置文件检查通过"
echo ""

# 检查模型目录
if [ ! -d "models/mineru/pipeline" ]; then
    echo "❌ 错误：模型目录不存在"
    echo "请运行: python scripts/migrate_mineru_models.py"
    exit 1
fi

echo "✅ 模型目录检查通过"
echo ""

# 启动服务
echo "启动 RAG 服务..."
echo "========================================="
echo ""

# 开发模式
if [ "$1" == "dev" ]; then
    echo "开发模式启动..."
    python main.py
# 生产模式
else
    echo "生产模式启动..."
    gunicorn -c deploy/gunicorn.conf.py deploy.wsgi:app
fi
