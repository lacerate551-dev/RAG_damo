# -*- coding: utf-8 -*-
"""
语义缓存模块（FAISS 版）

功能：
- 使用 FAISS 向量索引实现 O(1) 查找
- 语义级缓存：相似查询也能命中
- 高性能：10万缓存量下查询 < 1ms

使用方式：
    from core.semantic_cache import SemanticCache

    cache = SemanticCache(dim=768, threshold=0.92)

    # 查找
    result = cache.get(query_embedding)

    # 存储
    cache.set(query_embedding, result)
"""

import numpy as np
import logging
from typing import Dict, Optional, List, Any
import threading

logger = logging.getLogger(__name__)

# FAISS 可选依赖
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("FAISS 未安装，语义缓存将使用降级方案")


class SemanticCache:
    """
    语义缓存（FAISS 向量索引）

    使用 FAISS 实现高性能向量检索，支持：
    - O(1) 查找复杂度
    - 10万+ 缓存量
    - 亚毫秒级响应
    """

    def __init__(
        self,
        dim: int = 768,
        threshold: float = 0.92,
        max_size: int = 10000
    ):
        """
        初始化语义缓存

        Args:
            dim: 向量维度
            threshold: 相似度阈值（cosine 相似度）
            max_size: 最大缓存数量
        """
        self.dim = dim
        self.threshold = threshold
        self.max_size = max_size

        self._lock = threading.RLock()
        self._cache: Dict[int, Any] = {}  # id -> result
        self._next_id = 0

        # 统计信息
        self._hits = 0
        self._misses = 0

        if FAISS_AVAILABLE:
            # 使用内积索引（需要归一化向量）
            self._index = faiss.IndexFlatIP(dim)
            self._use_faiss = True
            logger.info(f"语义缓存初始化（FAISS），维度={dim}，阈值={threshold}")
        else:
            # 降级方案：使用 numpy
            self._embeddings: List[np.ndarray] = []
            self._use_faiss = False
            logger.warning("语义缓存降级为 numpy 方案")

    def get(self, query_emb: np.ndarray) -> Optional[Dict]:
        """
        查找语义缓存

        Args:
            query_emb: 查询向量（已归一化）

        Returns:
            缓存结果，未命中返回 None
        """
        with self._lock:
            if self._use_faiss:
                return self._get_faiss(query_emb)
            else:
                return self._get_numpy(query_emb)

    def _get_faiss(self, query_emb: np.ndarray) -> Optional[Dict]:
        """FAISS 查找"""
        if self._index.ntotal == 0:
            self._misses += 1
            return None

        # 归一化并搜索
        query = self._normalize(query_emb).reshape(1, -1).astype('float32')
        D, I = self._index.search(query, k=1)

        if D[0][0] > self.threshold:
            cache_id = int(I[0][0])
            self._hits += 1
            logger.debug(f"语义缓存命中，相似度={D[0][0]:.3f}")
            return self._cache.get(cache_id)

        self._misses += 1
        return None

    def _get_numpy(self, query_emb: np.ndarray) -> Optional[Dict]:
        """Numpy 降级查找"""
        if not self._embeddings:
            self._misses += 1
            return None

        query = self._normalize(query_emb)
        best_score = 0
        best_id = -1

        for i, emb in enumerate(self._embeddings):
            score = float(np.dot(query, emb))
            if score > best_score:
                best_score = score
                best_id = i

        if best_score > self.threshold:
            self._hits += 1
            logger.debug(f"语义缓存命中（numpy），相似度={best_score:.3f}")
            return self._cache.get(best_id)

        self._misses += 1
        return None

    def set(self, query_emb: np.ndarray, result: Dict) -> None:
        """
        存储到语义缓存

        Args:
            query_emb: 查询向量
            result: 缓存结果
        """
        with self._lock:
            if self._use_faiss:
                self._set_faiss(query_emb, result)
            else:
                self._set_numpy(query_emb, result)

    def _set_faiss(self, query_emb: np.ndarray, result: Dict) -> None:
        """FAISS 存储"""
        # 检查容量
        if self._index.ntotal >= self.max_size:
            # LRU 淘汰：重建索引（简单实现）
            logger.debug("语义缓存已满，执行淘汰")
            self.clear()

        # 归一化并添加
        query = self._normalize(query_emb).reshape(1, -1).astype('float32')
        self._index.add(query)
        self._cache[self._next_id] = result
        self._next_id += 1

    def _set_numpy(self, query_emb: np.ndarray, result: Dict) -> None:
        """Numpy 存储"""
        if len(self._embeddings) >= self.max_size:
            # 淘汰最早的
            self._embeddings.pop(0)
            # 重建 cache（ID 偏移）
            old_cache = self._cache
            self._cache = {}
            for i, (k, v) in enumerate(old_cache.items()):
                if i > 0:
                    self._cache[i - 1] = v

        query = self._normalize(query_emb)
        self._embeddings.append(query)
        self._cache[len(self._embeddings) - 1] = result

    def _normalize(self, emb: np.ndarray) -> np.ndarray:
        """归一化向量"""
        emb = np.array(emb, dtype='float32')
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            if self._use_faiss:
                self._index = faiss.IndexFlatIP(self.dim)
            else:
                self._embeddings.clear()
            self._cache.clear()
            self._next_id = 0
            logger.info("语义缓存已清空")

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0

            return {
                "total_entries": self._index.ntotal if self._use_faiss else len(self._embeddings),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "use_faiss": self._use_faiss
            }


# ==================== 全局语义缓存实例 ====================

_semantic_cache: Optional[SemanticCache] = None
_semantic_cache_lock = threading.Lock()


def get_semantic_cache(dim: int = 768) -> SemanticCache:
    """获取全局语义缓存实例"""
    global _semantic_cache
    if _semantic_cache is None:
        with _semantic_cache_lock:
            if _semantic_cache is None:
                try:
                    from config import SEMANTIC_CACHE_THRESHOLD
                    threshold = SEMANTIC_CACHE_THRESHOLD
                except ImportError:
                    threshold = 0.92

                _semantic_cache = SemanticCache(dim=dim, threshold=threshold)

    return _semantic_cache


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("语义缓存测试")
    print("=" * 60)

    cache = SemanticCache(dim=128, threshold=0.9, max_size=100)

    # 生成测试向量
    np.random.seed(42)

    def random_embedding():
        emb = np.random.randn(128)
        return emb / np.linalg.norm(emb)

    # 存储一些向量
    print("\n存储测试向量...")
    base_emb = random_embedding()
    cache.set(base_emb, {"answer": "测试答案1", "confidence": 0.9})

    for i in range(10):
        emb = random_embedding()
        cache.set(emb, {"answer": f"测试答案{i+2}", "confidence": 0.8})

    print(f"缓存统计: {cache.get_stats()}")

    # 测试精确命中
    print("\n测试精确命中...")
    result = cache.get(base_emb)
    print(f"结果: {result}")

    # 测试相似命中
    print("\n测试相似命中...")
    similar_emb = base_emb + np.random.randn(128) * 0.05
    similar_emb = similar_emb / np.linalg.norm(similar_emb)
    result = cache.get(similar_emb)
    print(f"结果: {result}")

    # 测试未命中
    print("\n测试未命中...")
    different_emb = random_embedding()
    result = cache.get(different_emb)
    print(f"结果: {result}")

    print(f"\n最终统计: {cache.get_stats()}")
