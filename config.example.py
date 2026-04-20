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

# ==================== Graph RAG 配置 ====================
# Neo4j 图数据库配置（可选，用于 Graph RAG）
# 安装方式: docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password123 neo4j:latest
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"

# Graph RAG 功能开关
USE_GRAPH_RAG = True  # 是否启用图谱检索

# 实体提取使用的模型（建议使用较强的模型）
GRAPH_EXTRACTION_MODEL = "qwen3.5-plus"

# ==================== RAG 路径配置 ====================
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 数据存储根目录（扁平化结构）
DATA_ROOT = os.path.join(PROJECT_ROOT, ".data")

# 模型路径
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
EMBEDDING_MODEL_PATH = os.path.join(MODELS_DIR, "bge-base-zh-v1.5")
RERANK_MODEL_PATH = os.path.join(MODELS_DIR, "bge-reranker-base")

# 向量库路径
VECTOR_STORE_PATH = os.path.join(PROJECT_ROOT, "knowledge", "vector_store")
CHROMA_DB_PATH = os.path.join(VECTOR_STORE_PATH, "chroma")

# 文档路径
DOCUMENTS_PATH = os.path.join(PROJECT_ROOT, "documents")

# BM25 索引路径
BM25_INDEXES_PATH = os.path.join(VECTOR_STORE_PATH, "bm25")

# 图片存储（扁平化）
IMAGES_DIR = os.path.join(DATA_ROOT, "images")

# 文档元数据存储
DOCSTORE_DIR = os.path.join(DATA_ROOT, "docstore")

# 缓存目录（扁平化）
CACHE_DIR = os.path.join(DATA_ROOT, "cache")
VLM_CACHE_DIR = os.path.join(CACHE_DIR, "vlm")
LLM_CACHE_DIR = os.path.join(CACHE_DIR, "llm")

# MinerU 临时输出（解析后自动清理）
MINERU_OUTPUT_DIR = os.path.join(DATA_ROOT, "mineru_temp")

# ==================== RAG 功能开关 ====================
USE_MULTI_KB = True           # 多向量库模式
USE_HYBRID_SEARCH = True      # 混合检索（向量 + BM25）
VECTOR_WEIGHT = 0.5           # 向量检索权重
BM25_WEIGHT = 0.5             # BM25 检索权重
USE_RERANK = True             # 重排序
RERANK_CANDIDATES = 20        # 重排序候选数量
RERANK_TOP_K = 5              # 重排序返回数量

# MinerU 解析配置（v5 统一解析器）
MINERU_BACKEND = "pipeline"   # 解析后端: pipeline, vlm-auto-engine, hybrid-auto-engine
MINERU_LANG = "ch"            # 语言代码
MINERU_TIMEOUT = 600          # 超时时间（秒）

# Excel 解析配置（Pandas 管道）
EXCEL_MAX_ROWS_PER_CHUNK = 200  # 大表切片阈值

# 分块配置
CHUNK_SIZE = 1000             # 基础分块大小
CHUNK_OVERLAP = 100           # 分块重叠

# ==================== 懒加载配置（Phase 4）====================
# 使用扁平化路径
VLM_CACHE_DIR = ".data/cache/vlm"  # VLM 描述缓存目录
LLM_CACHE_DIR = ".data/cache/llm"  # LLM 摘要缓存目录

# ==================== 富媒体展示配置（Phase 5）====================
MAX_IMAGES_PER_RESPONSE = 2   # 每次回答最多展示图片数
MIN_IMAGE_SCORE = 3.0         # 图片展示最低分数阈值

# ==================== 懒加载触发阈值 ====================
TABLE_SUMMARY_SCORE_THRESHOLD = 0.7  # 表格相关性 > 0.7 才生成摘要

# ==================== VLM 模型配置 ====================
DASHSCOPE_VL_MODEL = "qwen-vl-plus"  # 视觉模型（图片描述）