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
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
EMBEDDING_MODEL_PATH = os.path.join(MODELS_DIR, "bge-base-zh-v1.5")
RERANK_MODEL_PATH = os.path.join(MODELS_DIR, "bge-reranker-base")
VECTOR_STORE_PATH = os.path.join(PROJECT_ROOT, "vector_store")
CHROMA_DB_PATH = os.path.join(VECTOR_STORE_PATH, "chroma")
DOCUMENTS_PATH = os.path.join(PROJECT_ROOT, "documents")
BM25_INDEXES_PATH = os.path.join(VECTOR_STORE_PATH, "bm25")

# ==================== RAG 功能开关 ====================
USE_MULTI_KB = True           # 多向量库模式
USE_HYBRID_SEARCH = True      # 混合检索（向量 + BM25）
VECTOR_WEIGHT = 0.5           # 向量检索权重
BM25_WEIGHT = 0.5             # BM25 检索权重
USE_RERANK = True             # 重排序
RERANK_CANDIDATES = 20        # 重排序候选数量
RERANK_TOP_K = 5              # 重排序返回数量

# PDF 解析配置
USE_ODL_PARSER = True         # 使用 OpenDataLoader PDF 解析器
ODL_USE_STRUCT_TREE = True    # 使用 PDF 结构树
ODL_USE_HYBRID = False        # 混合模式（需后端服务）

# Docling 配置
USE_DOCLING_PARSER = True     # 使用 Docling 解析 Word

# Excel 解析配置
USE_EXCEL_ENHANCED = True     # 增强版 Excel 解析器
EXCEL_MAX_ROWS_PER_CHUNK = 50
EXCEL_MIN_ROWS_PER_CHUNK = 2

# 分块配置
USE_SEMANTIC_CHUNK = True     # 语义分块
SEMANTIC_BREAKPOINT_THRESHOLD = 0.5
SEMANTIC_MIN_CHUNK_SIZE = 50
SEMANTIC_MAX_CHUNK_SIZE = 800