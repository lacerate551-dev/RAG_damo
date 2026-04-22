# RAG 服务配置文件模板
# ================================
# 请复制为 config.py 并填入你的API密钥

import os

# ==============================================================================
# 一、核心 API 配置（必需）
# ==============================================================================

# 通义千问 API（LLM 服务）
DASHSCOPE_API_KEY = "your-dashscope-api-key-here"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_MODEL = "qwen-flash"           # 文本模型（表格摘要等）
DASHSCOPE_VL_MODEL = "qwen-vl-plus"      # 视觉模型（图片描述）

# Dify 工作流 API（出题/批阅，可选）
DIFY_API_URL = "https://api.dify.ai/v1"
DIFY_QUESTION_API_KEY = "your-dify-question-api-key"
DIFY_GRADE_API_KEY = "your-dify-grade-api-key"

# ==============================================================================
# 二、RAG 功能配置
# ==============================================================================

# ---------- 2.1 路径配置 ----------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
EMBEDDING_MODEL_PATH = os.path.join(MODELS_DIR, "bge-base-zh-v1.5")
RERANK_MODEL_PATH = os.path.join(MODELS_DIR, "bge-reranker-base")
VECTOR_STORE_PATH = os.path.join(PROJECT_ROOT, "knowledge", "vector_store")
CHROMA_DB_PATH = os.path.join(VECTOR_STORE_PATH, "chroma")
DOCUMENTS_PATH = os.path.join(PROJECT_ROOT, "documents")
BM25_INDEXES_PATH = os.path.join(VECTOR_STORE_PATH, "bm25")

# ---------- 2.2 检索配置 ----------
USE_MULTI_KB = True           # 多向量库模式
USE_HYBRID_SEARCH = True      # 混合检索（向量 + BM25）
VECTOR_WEIGHT = 0.5           # 向量检索权重
BM25_WEIGHT = 0.5             # BM25 检索权重
USE_RERANK = True             # 重排序
RERANK_CANDIDATES = 20        # 重排序候选数量
RERANK_TOP_K = 5              # 重排序返回数量

# ---------- 2.3 分块配置 ----------
CHUNK_SIZE = 1000             # 基础分块大小
CHUNK_OVERLAP = 100           # 分块重叠
MIN_CHUNK_SIZE = 200          # 最小切片大小（过短则合并）
MAX_CHUNK_SIZE = 1200         # 最大切片大小（过长则拆分）
SECTION_FILTER_ENABLED = True # 章节过滤开关

# ==============================================================================
# 三、缓存配置（P2 新增）
# ==============================================================================

# ---------- 3.1 查询缓存 ----------
QUERY_CACHE_ENABLED = True       # 是否启用查询缓存
QUERY_CACHE_SIZE = 500           # 查询缓存容量
QUERY_CACHE_TTL = 3600           # 查询缓存 TTL（秒）

# ---------- 3.2 Embedding 缓存 ----------
EMBEDDING_CACHE_ENABLED = True   # 是否启用 Embedding 缓存
EMBEDDING_CACHE_SIZE = 2000      # Embedding 缓存容量
EMBEDDING_CACHE_TTL = 86400      # Embedding 缓存 TTL（秒）

# ---------- 3.3 Rerank 缓存 ----------
RERANK_CACHE_ENABLED = True      # 是否启用 Rerank 缓存
RERANK_CACHE_SIZE = 1000         # Rerank 缓存容量
RERANK_CACHE_TTL = 3600          # Rerank 缓存 TTL（秒）

# ---------- 3.4 LLM 预算控制 ----------
MAX_LLM_CALLS_PER_QUERY = 2      # 每次查询最大 LLM 调用次数
MAX_QUERY_REWRITES = 1           # 每次查询最多重写次数

# ==============================================================================
# 四、文档解析配置
# ==============================================================================

# MinerU 解析配置（v5 统一解析器）
MINERU_BACKEND = "pipeline"   # 解析后端: pipeline, vlm-auto-engine, hybrid-auto-engine
MINERU_LANG = "ch"            # 语言代码
MINERU_TIMEOUT = 600          # 超时时间（秒）

# MinerU 模型路径（部署时需要配置）
MINERU_MODELS_DIR = os.getenv(
    "MINERU_MODELS_DIR",
    os.path.join(PROJECT_ROOT, "models", "mineru")
)

# Excel 解析配置
EXCEL_MAX_ROWS_PER_CHUNK = 200  # 大表切片阈值

# ==============================================================================
# 四、LLM 模型参数配置
# ==============================================================================

# ---------- 4.1 通用参数 ----------
LLM_TEMPERATURE = 0.7         # 默认温度
LLM_MAX_TOKENS = 2000         # 默认最大token数
LLM_TIMEOUT = 120             # 请求超时（秒）

# ---------- 4.2 分类/判断任务（低温度，高确定性）----------
LLM_CLASSIFY_TEMPERATURE = 0.1
LLM_CLASSIFY_MAX_TOKENS = 100

# ---------- 4.3 推理/分析任务 ----------
LLM_REASONING_TEMPERATURE = 0.3
LLM_REASONING_MAX_TOKENS = 1000

# ---------- 4.4 生成任务 ----------
LLM_GENERATION_TEMPERATURE = 0.7
LLM_GENERATION_MAX_TOKENS = 2000

# ---------- 4.5 FAQ扩写任务 ----------
LLM_FAQ_EXPANSION_TEMPERATURE = 0.7
LLM_FAQ_EXPANSION_MAX_TOKENS = 200

# ---------- 4.6 出题任务 ----------
LLM_QUESTION_TEMPERATURE = 0.7
LLM_QUESTION_MAX_TOKENS = 4000

# ---------- 4.7 批阅任务 ----------
LLM_GRADING_TEMPERATURE = 0.3
LLM_GRADING_MAX_TOKENS = 1000

# ==============================================================================
# 五、并发与性能配置
# ==============================================================================

# ---------- 5.1 服务配置 ----------
GUNICORN_WORKERS = int(os.getenv("GUNICORN_WORKERS", 0))  # 0=自动（CPU*2+1）
GUNICORN_TIMEOUT = 120       # 请求超时（秒）
GUNICORN_GRACEFUL_TIMEOUT = 30

# ---------- 5.2 并发控制 ----------
MAX_CONCURRENT_REQUESTS = 10  # 最大并发请求数
MAX_CONCURRENT_GRADING = 5    # 最大并发批阅数

# ---------- 5.3 线程池配置 ----------
THREAD_POOL_MAX_WORKERS = 5   # 线程池最大线程数

# ==============================================================================
# 六、设备配置（GPU/CPU）
# ==============================================================================

# 模型运行设备
# 可选值: "auto" | "cuda" | "cpu" | "cuda:0" | "cuda:1" | ...
# "auto" 会自动检测GPU，有GPU用GPU，无GPU用CPU
DEVICE = os.getenv("DEVICE", "auto")

# 向量模型设备（可单独配置，默认使用DEVICE）
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", DEVICE)

# Rerank模型设备（可单独配置，默认使用DEVICE）
RERANK_DEVICE = os.getenv("RERANK_DEVICE", DEVICE)

# ==============================================================================
# 六、环境控制（部署关键）
# ==============================================================================

APP_ENV = os.getenv("APP_ENV", "dev")
IS_DEV = APP_ENV == "dev"
IS_PROD = APP_ENV == "prod"

# ---------- 6.1 功能开关（根据环境自动切换）----------
ENABLE_SESSION = IS_DEV      # 会话管理仅开发环境
ENABLE_FEEDBACK = True       # 反馈系统保留（生产环境也需要）
ENABLE_AUDIT_LOG = IS_DEV    # 审计日志仅开发环境

# ---------- 6.2 扩展功能开关（手动控制）----------
ENABLE_WEB_SEARCH = False    # 网络搜索（需要 SERPER_API_KEY）
ENABLE_GRAPH_RAG = False     # 图谱检索（需要 Neo4j 数据库）
ENABLE_DIFY_WORKFLOW = False # Dify 工作流（后续扩展，当前使用本地LLM实现）

# ==============================================================================
# 七、LLM 客户端工厂
# ==============================================================================

def get_llm_client():
    """
    获取 LLM 客户端实例

    Returns:
        OpenAI 客户端实例
    """
    from openai import OpenAI
    return OpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL
    )

# ==============================================================================
# 八、可选/未启用配置
# ==============================================================================

# ---------- 8.1 Graph RAG 配置 ----------
# Neo4j 图数据库配置（启用 ENABLE_GRAPH_RAG 时需要）
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"
GRAPH_EXTRACTION_MODEL = "qwen3.5-plus"  # 实体提取模型

# RAG 对话模型配置（统一管理）
RAG_CHAT_MODEL = os.getenv("RAG_CHAT_MODEL", "qwen3.5-flash")  # RAG 对话模型（快速响应）

# 兼容旧变量名（内部代码仍使用 USE_GRAPH_RAG）
USE_GRAPH_RAG = ENABLE_GRAPH_RAG

# ---------- 8.2 网络搜索配置 ----------
# Serper API（启用 ENABLE_WEB_SEARCH 时需要）
SERPER_API_KEY = "your-serper-api-key"

# ---------- 8.3 兼容旧变量名（可移除）----------
API_KEY = DASHSCOPE_API_KEY
BASE_URL = DASHSCOPE_BASE_URL
MODEL = DASHSCOPE_MODEL
