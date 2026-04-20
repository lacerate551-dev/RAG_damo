"""
BM25 关键词检索索引

使用 rank_bm25 + jieba 分词实现中文关键词检索。
支持索引的序列化/反序列化。

使用方式：
    from core.bm25_index import BM25Index

    index = BM25Index()
    index.add_documents(ids, documents, metadatas)
    results = index.search("查询内容", top_k=5)
"""

import os
import pickle
import numpy as np
from rank_bm25 import BM25Okapi
import jieba


class BM25Index:
    """BM25索引管理器，用于关键词检索"""

    def __init__(self):
        self.bm25 = None
        self.documents = []  # 原始文档
        self.metadatas = []  # 元数据
        self.ids = []  # 文档ID

    def tokenize(self, text):
        """中文分词"""
        return list(jieba.cut(text))

    def add_documents(self, ids, documents, metadatas):
        """添加文档到索引"""
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas

        # 分词并构建BM25索引
        tokenized_docs = [self.tokenize(doc) for doc in documents]
        self.bm25 = BM25Okapi(tokenized_docs)

    def search(self, query, top_k=10):
        """BM25检索"""
        if not self.bm25:
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

        tokenized_query = self.tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        # 获取top_k个结果
        top_indices = np.argsort(scores)[::-1][:top_k]

        return {
            'ids': [[self.ids[i] for i in top_indices]],
            'documents': [[self.documents[i] for i in top_indices]],
            'metadatas': [[self.metadatas[i] for i in top_indices]],
            'distances': [[float(scores[i]) for i in top_indices]]
        }

    def save(self, path):
        """保存索引到文件"""
        data = {
            'ids': self.ids,
            'documents': self.documents,
            'metadatas': self.metadatas
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        print(f"      BM25索引已保存: {path}")

    def load(self, path):
        """从文件加载索引"""
        if not os.path.exists(path):
            return False

        with open(path, 'rb') as f:
            data = pickle.load(f)

        self.ids = data['ids']
        self.documents = data['documents']
        self.metadatas = data['metadatas']

        # 重建BM25索引
        tokenized_docs = [self.tokenize(doc) for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_docs)

        print(f"      BM25索引已加载: {len(self.documents)} 个文档")
        return True

    def clear(self):
        """清空索引"""
        self.bm25 = None
        self.documents = []
        self.metadatas = []
        self.ids = []


# ==================== 全局 BM25 索引管理器 ====================

_bm25_indexer: BM25Index = None


def get_bm25_indexer() -> BM25Index:
    """
    获取全局 BM25 索引器实例

    Returns:
        BM25Index 实例
    """
    global _bm25_indexer
    if _bm25_indexer is None:
        _bm25_indexer = BM25Index()
    return _bm25_indexer


def init_bm25_indexer(ids=None, documents=None, metadatas=None) -> BM25Index:
    """
    初始化 BM25 索引器并添加文档

    Args:
        ids: 文档 ID 列表
        documents: 文档内容列表
        metadatas: 元数据列表

    Returns:
        初始化后的 BM25Index 实例
    """
    global _bm25_indexer
    _bm25_indexer = BM25Index()
    if ids and documents:
        _bm25_indexer.add_documents(ids, documents, metadatas or [])
    return _bm25_indexer
