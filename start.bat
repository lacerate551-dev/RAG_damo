@echo off
REM RAG 服务启动脚本 - Windows 版本
REM 确保在项目根目录运行，并设置正确的环境变量

echo =========================================
echo RAG 服务启动脚本
echo =========================================
echo 项目目录: %CD%
echo.

REM 设置 MinerU 环境变量
set MINERU_MODEL_SOURCE=local
set MINERU_TOOLS_CONFIG_JSON=mineru.json

echo 环境变量设置：
echo   MINERU_MODEL_SOURCE=%MINERU_MODEL_SOURCE%
echo   MINERU_TOOLS_CONFIG_JSON=%MINERU_TOOLS_CONFIG_JSON%
echo.

REM 检查配置文件
if not exist "mineru.json" (
    echo ❌ 错误：mineru.json 配置文件不存在
    echo 请运行: copy mineru.json.template mineru.json
    pause
    exit /b 1
)

echo ✅ 配置文件检查通过
echo.

REM 检查模型目录
if not exist "models\mineru\pipeline" (
    echo ❌ 错误：模型目录不存在
    echo 请运行: python scripts\migrate_mineru_models.py
    pause
    exit /b 1
)

echo ✅ 模型目录检查通过
echo.

REM 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo ✅ 虚拟环境已激活
    echo.
)

REM 启动服务
echo 启动 RAG 服务...
echo =========================================
echo.

REM 开发模式
if "%1"=="dev" (
    echo 开发模式启动...
    python main.py
) else (
    REM 生产模式
    echo 生产模式启动...
    gunicorn -c deploy/gunicorn.conf.py deploy.wsgi:app
)
