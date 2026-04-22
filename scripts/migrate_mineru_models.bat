@echo off
REM MinerU 模型迁移脚本 - Windows 版本
REM
REM 功能：将 HuggingFace 缓存中的 MinerU 模型迁移到项目 models/ 目录

echo ========================================
echo MinerU 模型迁移工具
echo ========================================
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [错误] 虚拟环境不存在，请先创建虚拟环境
    echo 运行: python -m venv venv
    pause
    exit /b 1
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 运行迁移脚本
python scripts\migrate_mineru_models.py

REM 检查返回码
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo 迁移成功！
    echo ========================================
    echo.
    echo 下一步：
    echo 1. 测试解析: python parsers\mineru_parser.py documents\test.pdf
    echo 2. 删除缓存: rmdir /s "%%USERPROFILE%%\.cache\huggingface\hub\models--opendatalab--*"
    echo.
) else (
    echo.
    echo ========================================
    echo 迁移失败，请检查错误信息
    echo ========================================
    echo.
)

pause
