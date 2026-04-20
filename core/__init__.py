"""
RAG 核心引擎模块

包含：
- engine: RAGEngine 单例类，管理模型和共享资源
- agentic: AgenticRAG 智能问答
- bm25_index: BM25 关键词检索索引
- chunker: 文本分块器
"""

from .engine import RAGEngine, get_engine
from .bm25_index import BM25Index
from .chunker import split_text_with_limit, split_text

__all__ = [
    'RAGEngine', 'get_engine', 'BM25Index',
    'split_text_with_limit', 'split_text'
]
