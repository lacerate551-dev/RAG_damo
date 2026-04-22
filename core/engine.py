"""
RAG 核心引擎单例

封装由于历史原因散落在 rag_demo.py 中的全局变量及其核心操作，
包括模型加载、上下文状态维护、混合检索和底层问答。
"""

import os
import gc
import time
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb
from openai import OpenAI

from parsers import MINERU_AVAILABLE, PANDAS_AVAILABLE

# 缓存支持（延迟导入避免循环依赖）
try:
    from core.cache import get_cache_manager, RAGCacheManager
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

# 延迟导入，防止循环依赖
_engine_instance = None

try:
    from config import (
        API_KEY, BASE_URL, MODEL,
        MODELS_DIR, EMBEDDING_MODEL_PATH, RERANK_MODEL_PATH,
        CHROMA_DB_PATH, DOCUMENTS_PATH, BM25_INDEXES_PATH,
        USE_MULTI_KB, USE_HYBRID_SEARCH, VECTOR_WEIGHT, BM25_WEIGHT,
        USE_RERANK, RERANK_CANDIDATES, RERANK_TOP_K,
        CHUNK_SIZE, CHUNK_OVERLAP,
        # 设备配置
        EMBEDDING_DEVICE, RERANK_DEVICE,
        # 自适应 TopK 配置
        ADAPTIVE_TOPK_ENABLED, ADAPTIVE_LOW_CONFIDENCE, ADAPTIVE_HIGH_CONFIDENCE,
        ADAPTIVE_EXPAND_RATIO, ADAPTIVE_SHRINK_RATIO, ADAPTIVE_MIN_TOPK, ADAPTIVE_MAX_TOPK,
        # 切片配置
        MIN_CHUNK_SIZE, MAX_CHUNK_SIZE, SECTION_FILTER_ENABLED
    )
except ImportError:
    # 默认值
    ADAPTIVE_TOPK_ENABLED = True
    ADAPTIVE_LOW_CONFIDENCE = 0.5
    ADAPTIVE_HIGH_CONFIDENCE = 0.8
    ADAPTIVE_EXPAND_RATIO = 2.0
    ADAPTIVE_SHRINK_RATIO = 0.5
    ADAPTIVE_MIN_TOPK = 3
    ADAPTIVE_MAX_TOPK = 20
    MIN_CHUNK_SIZE = 200
    MAX_CHUNK_SIZE = 1200
    SECTION_FILTER_ENABLED = True
    EMBEDDING_DEVICE = "auto"
    RERANK_DEVICE = "auto"


def _get_device(device_config: str) -> str:
    """
    解析设备配置

    Args:
        device_config: 设备配置 ("auto", "cuda", "cpu", "cuda:0" 等)

    Returns:
        实际设备字符串
    """
    if device_config == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                print(f"[INFO] 检测到GPU: {torch.cuda.get_device_name(0)}")
                return device
            else:
                print("[INFO] 未检测到GPU，使用CPU")
                return "cpu"
        except ImportError:
            print("[INFO] PyTorch未安装，使用CPU")
            return "cpu"
    return device_config

from core.bm25_index import BM25Index


class RAGEngine:
    """RAG 引擎 - 单例模式，管理所有共享资源"""

    @classmethod
    def get_instance(cls) -> 'RAGEngine':
        global _engine_instance
        if _engine_instance is None:
            _engine_instance = cls()
        return _engine_instance

    def __init__(self):
        self.embedding_model = None
        self.reranker = None
        self.llm_client = None
        self.bm25_index = None

        # 单向量库模式
        self.chroma_client = None
        self.collection = None

        # 多向量库模式
        self.kb_manager = None
        self.kb_router = None

        # 自适应 TopK 策略
        self._adaptive_topk = None

        self._initialized = False

    def initialize(self):
        """显式初始化所有模型和数据库客户端"""
        global USE_RERANK
        if self._initialized:
            return

        print("=" * 50)
        print("初始化 RAG Engine 核心")
        print("=" * 50)

        os.makedirs(MODELS_DIR, exist_ok=True)

        # 1. 向量模型
        if os.path.exists(EMBEDDING_MODEL_PATH):
            device = _get_device(EMBEDDING_DEVICE)
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH, device=device)
            print(f"[OK] 向量模型加载完成: {EMBEDDING_MODEL_PATH} (设备: {device})")
        else:
            raise RuntimeError(f"向量模型未找到: {EMBEDDING_MODEL_PATH}")

        # 2. 向量数据库
        if USE_MULTI_KB:
            from knowledge.manager import KnowledgeBaseManager
            from knowledge.router import KnowledgeBaseRouter
            self.kb_manager = KnowledgeBaseManager(CHROMA_DB_PATH)
            self.kb_router = KnowledgeBaseRouter(use_llm=False)
            self.collection = self.kb_manager.get_collection('public_kb')
            print(f"[OK] 多向量库模式已启用")
        else:
            self.chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
            self.collection = self.chroma_client.get_or_create_collection(
                name="knowledge_base",
                metadata={"description": "RAG Demo 知识库"}
            )
            print(f"[OK] 单向量库模式已启用: {CHROMA_DB_PATH}")

        # 3. BM25 索引
        self.bm25_index = BM25Index()
        if USE_HYBRID_SEARCH and not USE_MULTI_KB:
            bm25_path = os.path.join(BM25_INDEXES_PATH, "default_bm25.pkl")
            self.bm25_index.load(bm25_path)
            print("[OK] BM25索引已加载")

        # 4. LLM 客户端
        self.llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        print(f"[OK] LLM 客户端就绪: {MODEL}")

        # 5. Reranker 模型
        if USE_RERANK:
            if os.path.exists(RERANK_MODEL_PATH):
                device = _get_device(RERANK_DEVICE)
                self.reranker = CrossEncoder(RERANK_MODEL_PATH, device=device)
                print(f"[OK] Rerank模型加载完成: {RERANK_MODEL_PATH} (设备: {device})")
            else:
                try:
                    os.makedirs(RERANK_MODEL_PATH, exist_ok=True)
                    from transformers import AutoModelForSequenceClassification, AutoTokenizer
                    model = AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-base")
                    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-base")
                    model.save_pretrained(RERANK_MODEL_PATH)
                    tokenizer.save_pretrained(RERANK_MODEL_PATH)
                except Exception as e:
                    print(f"[FAIL] Rerank模型加载失败: {e}")
                    USE_RERANK = False

        # 6. 自适应 TopK 策略
        if ADAPTIVE_TOPK_ENABLED:
            from core.adaptive_topk import AdaptiveConfig, AdaptiveTopK
            config = AdaptiveConfig(
                enabled=ADAPTIVE_TOPK_ENABLED,
                low_confidence_threshold=ADAPTIVE_LOW_CONFIDENCE,
                high_confidence_threshold=ADAPTIVE_HIGH_CONFIDENCE,
                expand_ratio=ADAPTIVE_EXPAND_RATIO,
                shrink_ratio=ADAPTIVE_SHRINK_RATIO,
                min_top_k=ADAPTIVE_MIN_TOPK,
                max_top_k=ADAPTIVE_MAX_TOPK
            )
            self._adaptive_topk = AdaptiveTopK(config)
            print(f"[OK] 自适应TopK已启用 (低={ADAPTIVE_LOW_CONFIDENCE}, 高={ADAPTIVE_HIGH_CONFIDENCE})")

        self._initialized = True

    # ---------------- 核心检索逻辑 ----------------

    def search_knowledge(self, query, top_k=5, allowed_levels=None, role=None, department=None, collections=None, source_filter=None):
        """
        混合检索逻辑封装

        Args:
            query: 查询文本
            top_k: 返回结果数量
            allowed_levels: 兏许访问的安全级别列表
            role: 用户角色（多向量库模式）
            department: 用户部门（多向量库模式）
            collections: 指定查询的向量库列表
            source_filter: 文件名过滤，精确匹配（如 "2604.09205v1.pdf"）
        """
        if not self._initialized:
            self.initialize()

        # ==================== 查询缓存检查 ====================
        cache_enabled = False
        if CACHE_AVAILABLE:
            try:
                from config import QUERY_CACHE_ENABLED
                cache_enabled = QUERY_CACHE_ENABLED
            except ImportError:
                cache_enabled = True  # 默认启用

            if cache_enabled:
                cache = get_cache_manager()
                # 确定缓存键的知识库名称
                kb_name = "public_kb"
                if USE_MULTI_KB and collections:
                    kb_name = collections[0] if len(collections) == 1 else "multi"

                cached_result = cache.get_query_result(query, kb_name)
                if cached_result is not None:
                    # 缓存命中，直接返回
                    return cached_result

        if USE_MULTI_KB and self.kb_manager:
            result = self._search_multi_kb(query, top_k, role, department, collections, source_filter=source_filter)
            # 缓存多知识库结果
            if cache_enabled and result.get('ids') and result['ids'][0]:
                top_dist = result['distances'][0][0] if result.get('distances') and result['distances'][0] else 1.0
                top_score = 1.0 - top_dist
                if top_score >= 0.3:
                    cache.set_query_result(query, kb_name, result)
            return result

        # 构建 where 条件（支持多个过滤条件组合）
        conditions = []
        if allowed_levels:
            conditions.append({"security_level": {"$in": allowed_levels}})
        if source_filter:
            conditions.append({"source": source_filter})

        where_filter = None
        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        query_vector = self.embedding_model.encode(query).tolist()
        recall_k = RERANK_CANDIDATES if (USE_RERANK or USE_HYBRID_SEARCH) else top_k
        recall_k = max(recall_k, top_k * 3)  # 确保有足够的候选

        query_kwargs = {
            "query_embeddings": [query_vector],
            "n_results": recall_k
        }
        if where_filter:
            query_kwargs["where"] = where_filter

        vector_results = self.collection.query(**query_kwargs)

        # ========== 独立查询 FAQ 集合 ==========
        faq_results = self._search_faq_collection(query_vector, top_k=3)
        if faq_results and faq_results.get('ids') and faq_results['ids'][0]:
            # 合并 FAQ 结果到主结果
            vector_results = self._merge_results([vector_results, faq_results])

        results_list = [vector_results]
        weights = [VECTOR_WEIGHT]

        if USE_HYBRID_SEARCH and self.bm25_index.bm25:
            bm25_results = self.bm25_index.search(query, top_k=recall_k)
            if where_filter and bm25_results['metadatas'][0]:
                allowed_set = set(allowed_levels)
                # 过滤 BM25 结果
                bm25_results = self._filter_results(bm25_results, lambda meta: meta.get('security_level', 'public') in allowed_set)
            results_list.append(bm25_results)
            weights.append(BM25_WEIGHT)

        if len(results_list) > 1:
            fused_results = self.reciprocal_rank_fusion(results_list, weights)
        else:
            fused_results = results_list[0]

        # 过滤废止切片
        fused_results = self._filter_deprecated_chunks(fused_results)

        # 章节过滤（如果查询中提到了章节）
        fused_results = self._filter_by_section(fused_results, query)

        if USE_RERANK and self.reranker:
            fused_results = self.rerank_results(query, fused_results, top_k)
        else:
            fused_results = self._truncate_results(fused_results, top_k)

        # FAQ 分数加权（Score Boosting）
        fused_results = self._boost_faq_chunks(fused_results)

        # 时间衰减（Time Decay）
        fused_results = self._apply_time_decay(fused_results)

        # 自适应 TopK：根据置信度调整返回数量
        if self._adaptive_topk and fused_results.get('distances') and fused_results['distances'][0]:
            top_score = 1.0 - fused_results['distances'][0][0]  # 距离转相似度
            adjusted_k, should_retrieve, reason = self._adaptive_topk.adjust(top_score, top_k)
            if "high_confidence" in reason:
                # 高置信度时截断结果
                fused_results = self._truncate_results(fused_results, adjusted_k)

        # ==================== 缓存结果 ====================
        if cache_enabled and fused_results.get('ids') and fused_results['ids'][0]:
            # 只缓存有结果且置信度较高的查询
            top_dist = fused_results['distances'][0][0] if fused_results.get('distances') and fused_results['distances'][0] else 1.0
            top_score = 1.0 - top_dist  # 距离转相似度
            if top_score >= 0.3:  # 置信度阈值
                cache.set_query_result(query, kb_name, fused_results)

        return fused_results

    def _search_faq_collection(self, query_vector: list, top_k: int = 3) -> dict:
        """
        独立查询 FAQ 集合

        FAQ 存储在独立的集合中，与普通文档分离，便于独立管理和清理

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量

        Returns:
            FAQ 检索结果
        """
        try:
            # 获取或创建 FAQ 集合
            if self.kb_manager:
                faq_collection = self.kb_manager.get_collection('faq_kb')
            else:
                faq_collection = self.chroma_client.get_or_create_collection(
                    name="faq_collection",
                    metadata={"description": "FAQ 专属向量库"}
                )

            if not faq_collection or faq_collection.count() == 0:
                return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

            # 查询 FAQ 集合
            results = faq_collection.query(
                query_embeddings=[query_vector],
                n_results=top_k
            )

            return results

        except Exception as e:
            print(f"FAQ 集合查询失败: {e}")
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

    def _merge_results(self, results_list: list) -> dict:
        """
        合并多个检索结果

        Args:
            results_list: 结果列表

        Returns:
            合并后的结果
        """
        all_ids = []
        all_docs = []
        all_metas = []
        all_dists = []

        for results in results_list:
            if results and results.get('ids') and results['ids'][0]:
                all_ids.extend(results['ids'][0])
                all_docs.extend(results['documents'][0])
                all_metas.extend(results['metadatas'][0])
                all_dists.extend(results['distances'][0])

        return {
            'ids': [all_ids],
            'documents': [all_docs],
            'metadatas': [all_metas],
            'distances': [all_dists]
        }

    def _boost_faq_chunks(self, results: dict) -> dict:
        """
        FAQ Chunk 分数加权

        FAQ 命中时分数提升 0.1，确保 FAQ 排名靠前
        注意：distances 是距离，越小越好，所以减去 0.1
        """
        if not results.get('metadatas') or not results['metadatas'][0]:
            return results

        for i, meta in enumerate(results['metadatas'][0]):
            if meta.get('chunk_type') == 'faq':
                # FAQ 加权：距离减小 = 相似度提升
                results['distances'][0][i] = max(0, results['distances'][0][i] - 0.1)

        return results

    def _apply_time_decay(self, results: dict, decay_months: int = 6) -> dict:
        """
        时间衰减：超过 N 个月的 FAQ 扣分

        防止过期 FAQ 成为"钉子户"，确保新内容有机会排在前面
        """
        from datetime import datetime

        if not results.get('metadatas') or not results['metadatas'][0]:
            return results

        now = datetime.now()
        for i, meta in enumerate(results['metadatas'][0]):
            if meta.get('chunk_type') == 'faq':
                created_at = meta.get('created_at')
                if created_at:
                    try:
                        created = datetime.fromisoformat(created_at)
                        age_months = (now - created).days / 30
                        if age_months > decay_months:
                            # 每超过一个月扣 0.01，最多扣 0.1
                            decay = min(0.1, (age_months - decay_months) * 0.01)
                            # 距离增加 = 相似度降低
                            results['distances'][0][i] += decay
                    except (ValueError, TypeError):
                        pass

        return results

    def filter_blacklisted_chunks(self, results: dict, blacklist: set) -> dict:
        """
        过滤黑名单 Chunk（负反馈降权机制）

        Args:
            results: 检索结果
            blacklist: 黑名单 source 集合

        Returns:
            过滤后的结果
        """
        if not blacklist or not results.get('metadatas') or not results['metadatas'][0]:
            return results

        f_ids, f_docs, f_metas, f_scores = [], [], [], []
        filtered_count = 0

        for bid, bdoc, bmeta, bscore in zip(
            results['ids'][0],
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ):
            source = bmeta.get('source', '')
            if source not in blacklist:
                f_ids.append(bid)
                f_docs.append(bdoc)
                f_metas.append(bmeta)
                f_scores.append(bscore)
            else:
                filtered_count += 1

        if filtered_count > 0:
            print(f"  过滤了 {filtered_count} 个黑名单 Chunk")

        return {
            'ids': [f_ids],
            'documents': [f_docs],
            'metadatas': [f_metas],
            'distances': [f_scores]
        }

    def _filter_results(self, results, condition_func):
        """通用结果过滤辅助函数"""
        f_ids, f_docs, f_metas, f_scores = [], [], [], []
        for bid, bdoc, bmeta, bscore in zip(
            results['ids'][0], results['documents'][0],
            results['metadatas'][0], results['distances'][0]
        ):
            if condition_func(bmeta):
                f_ids.append(bid)
                f_docs.append(bdoc)
                f_metas.append(bmeta)
                f_scores.append(bscore)
        return {
            'ids': [f_ids],
            'documents': [f_docs],
            'metadatas': [f_metas],
            'distances': [f_scores]
        }

    def _truncate_results(self, results, top_k):
        """截断结果到指定的 top_k"""
        if not results.get('ids') or not results['ids'][0]:
            return results
        return {
            'ids': [results['ids'][0][:top_k]],
            'documents': [results['documents'][0][:top_k]],
            'metadatas': [results['metadatas'][0][:top_k]],
            'distances': [results['distances'][0][:top_k]]
        }

    def _search_multi_kb(self, query, top_k=5, role=None, department=None, target_collections=None, source_filter=None):
        """
        多向量库检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            role: 用户角色
            department: 用户部门
            target_collections: 指定查询的向量库列表
            source_filter: 文件名过滤，精确匹配
        """
        if target_collections is None:
            if role and department:
                from auth.gateway import get_accessible_collections
                accessible = get_accessible_collections(role, department, 'read')
                target_collections = self.kb_router.route(query, role, department, accessible)
            else:
                target_collections = ['public_kb']

        if not target_collections:
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

        query_vector = self.embedding_model.encode(query).tolist()
        # 扩大召回数量，以便过滤废止切片后仍有足够结果
        recall_k = RERANK_CANDIDATES if (USE_RERANK or USE_HYBRID_SEARCH) else top_k
        recall_k = max(recall_k, top_k * 3)  # 确保有足够的候选

        all_results = []
        for coll_name in target_collections:
            try:
                coll = self.kb_manager.get_collection(coll_name)
                if not coll: continue

                # 构建 where 过滤条件（排除废止切片）
                # ChromaDB 不支持 != 操作，需要在查询后过滤
                query_kwargs = {
                    "query_embeddings": [query_vector],
                    "n_results": recall_k
                }
                if source_filter:
                    query_kwargs["where"] = {"source": source_filter}

                results = coll.query(**query_kwargs)
                if results['metadatas'] and results['metadatas'][0]:
                    for meta in results['metadatas'][0]:
                        meta['_collection'] = coll_name
                all_results.append(results)

                if USE_HYBRID_SEARCH:
                    try:
                        bm25 = self.kb_manager.get_bm25_index(coll_name)
                        if bm25.bm25:
                            bm25_res = bm25.search(query, top_k=recall_k)
                            # 对 BM25 结果应用 source 过滤
                            if source_filter and bm25_res['metadatas'] and bm25_res['metadatas'][0]:
                                bm25_res = self._filter_results(bm25_res, lambda meta: meta.get('source') == source_filter)
                            if bm25_res['metadatas'] and bm25_res['metadatas'][0]:
                                for meta in bm25_res['metadatas'][0]:
                                    meta['_collection'] = coll_name
                                all_results.append(bm25_res)
                    except Exception: pass
            except Exception: continue

        # ========== FAQ 检索 ==========
        faq_results = self._search_faq_collection(query_vector, top_k=3)
        if faq_results and faq_results.get('ids') and faq_results['ids'][0]:
            for meta in faq_results['metadatas'][0]:
                meta['_collection'] = 'faq_kb'
            all_results.append(faq_results)

        if not all_results:
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

        if len(all_results) == 1:
            fused_results = all_results[0]
        else:
            weights = [VECTOR_WEIGHT if i % 2 == 0 else BM25_WEIGHT for i in range(len(all_results))]
            fused_results = self.reciprocal_rank_fusion(all_results, weights)

        # 过滤废止切片（status != "active" 或 status == "deprecated"）
        fused_results = self._filter_deprecated_chunks(fused_results)

        # 章节过滤（如果查询中提到了章节）
        fused_results = self._filter_by_section(fused_results, query)

        if USE_RERANK and self.reranker:
            fused_results = self.rerank_results(query, fused_results, top_k)
        else:
            fused_results = self._truncate_results(fused_results, top_k)

        # FAQ 分数加权
        fused_results = self._boost_faq_chunks(fused_results)

        # 时间衰减
        fused_results = self._apply_time_decay(fused_results)

        # 自适应 TopK：根据置信度调整返回数量
        if self._adaptive_topk and fused_results.get('distances') and fused_results['distances'][0]:
            top_score = 1.0 - fused_results['distances'][0][0]  # 距离转相似度
            adjusted_k, should_retrieve, reason = self._adaptive_topk.adjust(top_score, top_k)
            if "high_confidence" in reason:
                # 高置信度时截断结果
                fused_results = self._truncate_results(fused_results, adjusted_k)

        return fused_results

    def _filter_deprecated_chunks(self, results: dict) -> dict:
        """
        过滤废止切片，只保留 active 状态的切片

        Args:
            results: 检索结果

        Returns:
            过滤后的结果
        """
        if not results['metadatas'] or not results['metadatas'][0]:
            return results

        filtered_ids = []
        filtered_docs = []
        filtered_metas = []
        filtered_distances = []

        for i, (doc_id, doc, meta, dist) in enumerate(zip(
            results['ids'][0],
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0] if results['distances'] else [0] * len(results['ids'][0])
        )):
            # 只保留 active 状态的切片（未标记或标记为 active）
            status = meta.get('status', 'active')
            if status == 'active':
                filtered_ids.append(doc_id)
                filtered_docs.append(doc)
                filtered_metas.append(meta)
                filtered_distances.append(dist)

        return {
            'ids': [filtered_ids],
            'documents': [filtered_docs],
            'metadatas': [filtered_metas],
            'distances': [filtered_distances]
        }

    def _filter_by_section(self, results: dict, query: str) -> dict:
        """
        根据查询中的章节信息过滤结果

        如果查询中明确提到了章节（如"第一章"、"一、"），则优先返回该章节的切片。

        Args:
            results: 检索结果
            query: 用户查询

        Returns:
            过滤后的结果
        """
        if not SECTION_FILTER_ENABLED:
            return results

        if not results['metadatas'] or not results['metadatas'][0]:
            return results

        # 从查询中提取章节关键词
        import re
        section_patterns = [
            r'第[一二三四五六七八九十\d]+章',
            r'第\s*\d+\s*章',
            r'[一二三四五六七八九十]+、',
        ]

        mentioned_sections = []
        for pattern in section_patterns:
            matches = re.findall(pattern, query)
            mentioned_sections.extend(matches)

        if not mentioned_sections:
            return results

        # 过滤切片
        filtered_ids = []
        filtered_docs = []
        filtered_metas = []
        filtered_distances = []

        for i, (doc_id, doc, meta, dist) in enumerate(zip(
            results['ids'][0],
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0] if results['distances'] else [0] * len(results['ids'][0])
        )):
            section = meta.get('section', meta.get('section_path', ''))

            # 检查是否匹配任一章节
            for section_kw in mentioned_sections:
                if section_kw in section or section_kw in doc:
                    filtered_ids.append(doc_id)
                    filtered_docs.append(doc)
                    filtered_metas.append(meta)
                    filtered_distances.append(dist)
                    break

        # 如果过滤后结果为空，返回原始结果
        if not filtered_ids:
            return results

        return {
            'ids': [filtered_ids],
            'documents': [filtered_docs],
            'metadatas': [filtered_metas],
            'distances': [filtered_distances]
        }

    # ---------------- 底层融合辅助算法 ----------------

    def reciprocal_rank_fusion(self, results_list, weights=None, k=60):
        if not results_list:
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}
        if weights is None:
            weights = [1.0] * len(results_list)

        doc_scores = {}
        for results, weight in zip(results_list, weights):
            if not results['documents'] or not results['documents'][0]:
                continue
            for rank, (doc_id, doc, meta) in enumerate(zip(
                results['ids'][0], results['documents'][0], results['metadatas'][0]
            )):
                rrf_score = weight / (k + rank + 1)
                if doc_id not in doc_scores:
                    doc_scores[doc_id] = {'score': 0.0, 'doc': doc, 'meta': meta}
                doc_scores[doc_id]['score'] += rrf_score

        sorted_items = sorted(doc_scores.items(), key=lambda x: x[1]['score'], reverse=True)
        return {
            'ids': [[item[0] for item in sorted_items]],
            'documents': [[item[1]['doc'] for item in sorted_items]],
            'metadatas': [[item[1]['meta'] for item in sorted_items]],
            'distances': [[item[1]['score'] for item in sorted_items]]
        }

    def rerank_results(self, query, results, top_k=5):
        if not self.reranker or not results['documents'][0]:
            return results
        pairs = [(query, doc) for doc in results['documents'][0]]
        scores = self.reranker.predict(pairs)
        sorted_indices = np.argsort(scores)[::-1]
        return {
            'ids': [[results['ids'][0][i] for i in sorted_indices[:top_k]]],
            'documents': [[results['documents'][0][i] for i in sorted_indices[:top_k]]],
            'metadatas': [[results['metadatas'][0][i] for i in sorted_indices[:top_k]]],
            'distances': [[float(scores[i]) for i in sorted_indices[:top_k]]]
        }

    # ---------------- 安全与工具 ----------------

    def check_restricted_documents(self, query, allowed_levels, top_k=3, role=None, department=None):
        if not self._initialized:
            self.initialize()

        if USE_MULTI_KB and self.kb_manager and role and department:
            from auth.gateway import get_accessible_collections
            all_colls = [c.name for c in self.kb_manager.list_collections()]
            accessible = set(get_accessible_collections(role, department, 'read'))
            restricted = set(all_colls) - accessible

            if not restricted:
                return {"has_restricted": False, "restricted_levels": [], "restricted_sources": []}

            query_vector = self.embedding_model.encode(query).tolist()
            found_sources = set()
            top_score = 0.0

            for coll_name in restricted:
                try:
                    coll = self.kb_manager.get_collection(coll_name)
                    if not coll: continue
                    res = coll.query(query_embeddings=[query_vector], n_results=top_k)
                    if res['metadatas'] and res['metadatas'][0]:
                        for meta in res['metadatas'][0]:
                            found_sources.add(meta.get('source', '未知'))
                        for dist in (res.get('distances', [[]])[0] or []):
                            if dist > top_score: top_score = dist
                except Exception: pass

            return {
                "has_restricted": len(found_sources) > 0,
                "restricted_levels": [c.replace('dept_', '') for c in restricted if True][:3],
                "restricted_sources": list(found_sources)[:3],
                "top_restricted_score": top_score
            }

        if not allowed_levels:
            return {"has_restricted": False, "restricted_levels": [], "restricted_sources": [], "top_restricted_score": 0.0}

        restricted_levels = {"public", "internal", "confidential", "secret"} - set(allowed_levels)
        if not restricted_levels:
            return {"has_restricted": False, "restricted_levels": [], "restricted_sources": [], "top_restricted_score": 0.0}

        query_vector = self.embedding_model.encode(query).tolist()
        try:
            res = self.collection.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                where={"security_level": {"$in": list(restricted_levels)}}
            )
            docs = res.get('documents', [[]])[0]
            if not docs:
                return {"has_restricted": False, "restricted_levels": [], "restricted_sources": [], "top_restricted_score": 0.0}

            metas = res.get('metadatas', [[]])[0]
            dists = res.get('distances', [[]])[0]
            found_levels, found_sources, top_score = set(), set(), 0.0

            for meta, dist in zip(metas, dists):
                found_levels.add(meta.get('security_level', 'public'))
                found_sources.add(meta.get('source', '未知'))
                if dist > top_score: top_score = dist

            return {
                "has_restricted": True,
                "restricted_levels": list(found_levels),
                "restricted_sources": list(found_sources)[:3],
                "top_restricted_score": top_score
            }
        except Exception:
            return {"has_restricted": False, "restricted_levels": [], "restricted_sources": [], "top_restricted_score": 0.0}

    def generate_answer(self, query, context):
        """底层生成答复能力"""
        prompt = f"""你是一个严谨的智能助手，请根据以下参考资料回答用户的问题。
...
参考资料：
{context}

用户问题：{query}

请回答："""
        try:
            resp = self.llm_client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1500
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"调用大模型失败: {str(e)}"

    def generate_answer_stream(self, query, context, history=None):
        """
        流式生成答复

        Args:
            query: 用户问题
            context: 检索到的上下文
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]

        Yields:
            str: 每个 token
        """
        # 构建消息列表
        messages = []

        # 添加历史对话
        if history:
            for h in history:
                messages.append({
                    "role": h.get("role", "user"),
                    "content": h.get("content", "")
                })

        # 添加当前问题（带上下文）
        if context:
            user_message = f"""参考资料：
{context}

用户问题：{query}

请根据参考资料回答问题："""
        else:
            user_message = query

        messages.append({"role": "user", "content": user_message})

        try:
            stream = self.llm_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
                stream=True  # 启用流式输出
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"[错误] 调用大模型失败: {str(e)}"


# 快捷访问单例
def get_engine() -> RAGEngine:
    engine = RAGEngine.get_instance()
    if not engine._initialized:
        engine.initialize()
    return engine
