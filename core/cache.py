# -*- coding: utf-8 -*-
"""
RAG 三层缓存模块

缓存层次：
1. Query Cache: 完整问答结果缓存
2. Embedding Cache: 向量化结果缓存
3. Rerank Cache: 重排序分数缓存

缓存失效：基于知识库版本号（kb_version）的自动失效机制
"""

import hashlib
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float
    ttl: float  # 秒
    hits: int = 0
    kb_version: int = 0

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


@dataclass
class CacheStats:
    """缓存统计"""
    total_entries: int = 0
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class LRUCache:
    """线程安全的 LRU 缓存实现"""

    def __init__(self, max_size: int = 1000, default_ttl: float = 3600):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key not in self._cache:
                self._stats.misses += 1
                return None

            entry = self._cache[key]

            # 检查过期
            if entry.is_expired():
                del self._cache[key]
                self._stats.misses += 1
                self._stats.evictions += 1
                return None

            # LRU 更新
            self._cache.move_to_end(key)
            entry.hits += 1
            self._stats.hits += 1

            return entry.value

    def set(self, key: str, value: Any, ttl: float = None,
            kb_version: int = 0) -> None:
        """设置缓存值"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]

            entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl or self.default_ttl,
                kb_version=kb_version
            )

            self._cache[key] = entry

            # LRU 淘汰
            while len(self._cache) > self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._stats.evictions += 1

            self._stats.total_entries = len(self._cache)

    def invalidate_by_version(self, kb_version: int) -> int:
        """失效指定版本的所有缓存"""
        count = 0
        with self._lock:
            keys_to_delete = [
                k for k, v in self._cache.items()
                if v.kb_version == kb_version
            ]
            for key in keys_to_delete:
                del self._cache[key]
                count += 1
            self._stats.evictions += count
            self._stats.total_entries = len(self._cache)
        return count

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._stats.total_entries = 0

    def get_stats(self) -> CacheStats:
        """获取统计信息"""
        with self._lock:
            return self._stats


class RAGCacheManager:
    """RAG 三层缓存管理器"""

    # 默认配置（可从 config 覆盖）
    DEFAULT_QUERY_CACHE_SIZE = 500
    DEFAULT_QUERY_CACHE_TTL = 3600  # 1小时

    DEFAULT_EMBEDDING_CACHE_SIZE = 2000
    DEFAULT_EMBEDDING_CACHE_TTL = 86400  # 24小时

    DEFAULT_RERANK_CACHE_SIZE = 1000
    DEFAULT_RERANK_CACHE_TTL = 3600  # 1小时

    def __init__(
        self,
        query_cache_size: int = None,
        query_cache_ttl: float = None,
        embedding_cache_size: int = None,
        embedding_cache_ttl: float = None,
        rerank_cache_size: int = None,
        rerank_cache_ttl: float = None,
        kb_versions: Dict[str, int] = None
    ):
        """初始化缓存管理器"""
        self.query_cache = LRUCache(
            max_size=query_cache_size or self.DEFAULT_QUERY_CACHE_SIZE,
            default_ttl=query_cache_ttl or self.DEFAULT_QUERY_CACHE_TTL
        )
        self.embedding_cache = LRUCache(
            max_size=embedding_cache_size or self.DEFAULT_EMBEDDING_CACHE_SIZE,
            default_ttl=embedding_cache_ttl or self.DEFAULT_EMBEDDING_CACHE_TTL
        )
        self.rerank_cache = LRUCache(
            max_size=rerank_cache_size or self.DEFAULT_RERANK_CACHE_SIZE,
            default_ttl=rerank_cache_ttl or self.DEFAULT_RERANK_CACHE_TTL
        )

        self._kb_versions: Dict[str, int] = kb_versions or {}
        self._version_lock = threading.Lock()

    def get_kb_version(self, kb_name: str) -> int:
        """获取知识库当前版本号"""
        with self._version_lock:
            return self._kb_versions.get(kb_name, 0)

    def increment_kb_version(self, kb_name: str) -> int:
        """递增知识库版本号（文档更新时调用）"""
        with self._version_lock:
            old_version = self._kb_versions.get(kb_name, 0)
            self._kb_versions[kb_name] = old_version + 1
            new_version = self._kb_versions[kb_name]

        # 失效旧版本缓存
        self.query_cache.invalidate_by_version(old_version)
        self.embedding_cache.invalidate_by_version(old_version)

        logger.info(f"知识库 {kb_name} 版本更新: {old_version} -> {new_version}")
        return new_version

    # ==================== Query Cache 方法 ====================

    @staticmethod
    def _make_query_cache_key(query: str, kb_name: str, kb_version: int) -> str:
        return hashlib.md5(
            f"query:{query}:{kb_name}:{kb_version}".encode()
        ).hexdigest()

    def get_query_result(self, query: str, kb_name: str) -> Optional[Dict]:
        """获取查询缓存结果"""
        kb_version = self.get_kb_version(kb_name)
        key = self._make_query_cache_key(query, kb_name, kb_version)
        return self.query_cache.get(key)

    def set_query_result(self, query: str, kb_name: str, result: Dict) -> None:
        """设置查询缓存结果"""
        kb_version = self.get_kb_version(kb_name)
        key = self._make_query_cache_key(query, kb_name, kb_version)
        self.query_cache.set(key, result, kb_version=kb_version)

    # ==================== Embedding Cache 方法 ====================

    @staticmethod
    def _make_embedding_key(text: str) -> str:
        return hashlib.md5(f"emb:{text}".encode()).hexdigest()

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本的 Embedding 缓存"""
        key = self._make_embedding_key(text)
        return self.embedding_cache.get(key)

    def set_embedding(self, text: str, embedding: List[float],
                      kb_version: int = 0) -> None:
        """设置 Embedding 缓存"""
        key = self._make_embedding_key(text)
        self.embedding_cache.set(key, embedding, kb_version=kb_version)

    def get_embeddings_batch(self, texts: List[str]) -> Tuple[List[Optional[List[float]]], List[int]]:
        """
        批量获取 Embedding

        Returns:
            (embeddings, missed_indices): 命中的 embedding 列表（未命中为 None）和未命中的索引列表
        """
        embeddings: List[Optional[List[float]]] = []
        missed_indices: List[int] = []

        for i, text in enumerate(texts):
            emb = self.get_embedding(text)
            if emb is not None:
                embeddings.append(emb)
            else:
                embeddings.append(None)
                missed_indices.append(i)

        return embeddings, missed_indices

    # ==================== Rerank Cache 方法 ====================

    @staticmethod
    def _make_rerank_key(query: str, doc_ids: List[str]) -> str:
        sorted_ids = sorted(doc_ids)
        return hashlib.md5(
            f"rerank:{query}:{':'.join(sorted_ids)}".encode()
        ).hexdigest()

    def get_rerank_scores(self, query: str, doc_ids: List[str]) -> Optional[List[float]]:
        """获取 Rerank 分数缓存"""
        key = self._make_rerank_key(query, doc_ids)
        return self.rerank_cache.get(key)

    def set_rerank_scores(self, query: str, doc_ids: List[str],
                          scores: List[float]) -> None:
        """设置 Rerank 分数缓存"""
        key = self._make_rerank_key(query, doc_ids)
        self.rerank_cache.set(key, scores)

    # ==================== 统计方法 ====================

    def get_all_stats(self) -> Dict[str, CacheStats]:
        """获取所有缓存的统计信息"""
        return {
            "query_cache": self.query_cache.get_stats(),
            "embedding_cache": self.embedding_cache.get_stats(),
            "rerank_cache": self.rerank_cache.get_stats()
        }

    def clear_all(self) -> None:
        """清空所有缓存"""
        self.query_cache.clear()
        self.embedding_cache.clear()
        self.rerank_cache.clear()
        logger.info("所有缓存已清空")


# ==================== 全局缓存实例 ====================

_cache_manager: Optional[RAGCacheManager] = None
_cache_lock = threading.Lock()


def get_cache_manager() -> RAGCacheManager:
    """获取全局缓存管理器实例（单例模式）"""
    global _cache_manager
    if _cache_manager is None:
        with _cache_lock:
            if _cache_manager is None:
                # 尝试从配置加载参数
                try:
                    from config import (
                        QUERY_CACHE_SIZE, QUERY_CACHE_TTL,
                        EMBEDDING_CACHE_SIZE, EMBEDDING_CACHE_TTL,
                        RERANK_CACHE_SIZE, RERANK_CACHE_TTL
                    )
                    _cache_manager = RAGCacheManager(
                        query_cache_size=QUERY_CACHE_SIZE,
                        query_cache_ttl=QUERY_CACHE_TTL,
                        embedding_cache_size=EMBEDDING_CACHE_SIZE,
                        embedding_cache_ttl=EMBEDDING_CACHE_TTL,
                        rerank_cache_size=RERANK_CACHE_SIZE,
                        rerank_cache_ttl=RERANK_CACHE_TTL
                    )
                except ImportError:
                    # 使用默认配置
                    _cache_manager = RAGCacheManager()
    return _cache_manager


def reset_cache_manager() -> None:
    """重置全局缓存管理器（主要用于测试）"""
    global _cache_manager
    with _cache_lock:
        if _cache_manager is not None:
            _cache_manager.clear_all()
        _cache_manager = None


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("缓存模块测试")
    print("=" * 60)

    cache = RAGCacheManager()

    # 测试 Query Cache
    print("\n1. Query Cache 测试")
    cache.set_query_result("什么是Python?", "public_kb", {"answer": "Python是一种编程语言"})
    result = cache.get_query_result("什么是Python?", "public_kb")
    print(f"   缓存命中: {result}")

    # 测试版本号失效
    print("\n2. 版本号失效测试")
    cache.increment_kb_version("public_kb")
    result = cache.get_query_result("什么是Python?", "public_kb")
    print(f"   版本更新后缓存失效: {result is None}")

    # 测试 Embedding Cache
    print("\n3. Embedding Cache 测试")
    cache.set_embedding("测试文本", [0.1, 0.2, 0.3])
    emb = cache.get_embedding("测试文本")
    print(f"   Embedding 缓存: {emb}")

    # 测试统计
    print("\n4. 缓存统计")
    stats = cache.get_all_stats()
    for name, stat in stats.items():
        print(f"   {name}: hits={stat.hits}, misses={stat.misses}, hit_rate={stat.hit_rate:.2%}")
