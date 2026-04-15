"""
RAG 核心引擎模块

包含：
- engine: RAGEngine 单例类，管理模型和共享资源
- agentic: AgenticRAG 智能问答
- bm25_index: BM25 关键词检索索引
- chunker: 语义分块器
"""

from .engine import RAGEngine, get_engine
from .bm25_index import BM25Index

try:
    from .chunker import SemanticChunker, HybridChunker
except ImportError:
    pass

__all__ = [
    'RAGEngine', 'get_engine', 'BM25Index',
    'SemanticChunker', 'HybridChunker'
]
