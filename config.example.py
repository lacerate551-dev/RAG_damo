# API配置 - 请复制为 config.py 并填入你的API Key

# 通义千问API配置（必需）
DASHSCOPE_API_KEY = "your-dashscope-api-key-here"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_MODEL = "qwen3.5-plus"

# Serper API（可选，用于网络搜索）
# 注册地址: https://serper.dev/
SERPER_API_KEY = "your-serper-api-key-here"

# Dify工作流API配置（可选，用于智能出题）
DIFY_API_URL = "https://api.dify.ai/v1"
DIFY_QUESTION_API_KEY = "your-dify-question-api-key-here"  # 出题工作流
DIFY_GRADE_API_KEY = "your-dify-grade-api-key-here"        # 批阅工作流

# 兼容旧变量名
API_KEY = DASHSCOPE_API_KEY
BASE_URL = DASHSCOPE_BASE_URL
MODEL = DASHSCOPE_MODEL