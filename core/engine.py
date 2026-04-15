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

from parsers import ODL_AVAILABLE, DOCLING_AVAILABLE, EXCEL_ENHANCED_AVAILABLE

# 延迟导入，防止循环依赖
_engine_instance = None

try:
    from config import (
        API_KEY, BASE_URL, MODEL,
        MODELS_DIR, EMBEDDING_MODEL_PATH, RERANK_MODEL_PATH,
        CHROMA_DB_PATH, DOCUMENTS_PATH, BM25_INDEXES_PATH,
        USE_MULTI_KB, USE_HYBRID_SEARCH, VECTOR_WEIGHT, BM25_WEIGHT,
        USE_RERANK, RERANK_CANDIDATES, RERANK_TOP_K,
        USE_SEMANTIC_CHUNK, SEMANTIC_BREAKPOINT_THRESHOLD,
        SEMANTIC_MIN_CHUNK_SIZE, SEMANTIC_MAX_CHUNK_SIZE
    )
except ImportError:
    pass

from core.bm25_index import BM25Index

try:
    from core.chunker import SemanticChunker, HybridChunker
    SEMANTIC_CHUNKER_AVAILABLE = True
except ImportError:
    SEMANTIC_CHUNKER_AVAILABLE = False


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
        self.semantic_chunker = None
        self.bm25_index = None

        # 单向量库模式
        self.chroma_client = None
        self.collection = None

        # 多向量库模式
        self.kb_manager = None
        self.kb_router = None

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
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
            print(f"✓ 向量模型加载完成: {EMBEDDING_MODEL_PATH}")
        else:
            raise RuntimeError(f"向量模型未找到: {EMBEDDING_MODEL_PATH}")

        # 设置语义分块器
        if USE_SEMANTIC_CHUNK and SEMANTIC_CHUNKER_AVAILABLE:
            self.semantic_chunker = SemanticChunker(
                embedding_model=self.embedding_model,
                breakpoint_threshold=SEMANTIC_BREAKPOINT_THRESHOLD,
                min_chunk_size=SEMANTIC_MIN_CHUNK_SIZE,
                max_chunk_size=SEMANTIC_MAX_CHUNK_SIZE
            )

        # 2. 向量数据库
        if USE_MULTI_KB:
            from knowledge.manager import KnowledgeBaseManager
            from knowledge.router import KnowledgeBaseRouter
            self.kb_manager = KnowledgeBaseManager(CHROMA_DB_PATH)
            self.kb_router = KnowledgeBaseRouter(use_llm=False)
            self.collection = self.kb_manager.get_collection('public_kb')
            print(f"✓ 多向量库模式已启用")
        else:
            self.chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
            self.collection = self.chroma_client.get_or_create_collection(
                name="knowledge_base",
                metadata={"description": "RAG Demo 知识库"}
            )
            print(f"✓ 单向量库模式已启用: {CHROMA_DB_PATH}")

        # 3. BM25 索引
        self.bm25_index = BM25Index()
        if USE_HYBRID_SEARCH and not USE_MULTI_KB:
            bm25_path = os.path.join(BM25_INDEXES_PATH, "default_bm25.pkl")
            self.bm25_index.load(bm25_path)
            print("✓ BM25索引已加载")

        # 4. LLM 客户端
        self.llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        print(f"✓ LLM 客户端就绪: {MODEL}")

        # 5. Reranker 模型
        if USE_RERANK:
            if os.path.exists(RERANK_MODEL_PATH):
                self.reranker = CrossEncoder(RERANK_MODEL_PATH)
                print(f"✓ Rerank模型加载完成: {RERANK_MODEL_PATH}")
            else:
                try:
                    os.makedirs(RERANK_MODEL_PATH, exist_ok=True)
                    from transformers import AutoModelForSequenceClassification, AutoTokenizer
                    model = AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-base")
                    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-base")
                    model.save_pretrained(RERANK_MODEL_PATH)
                    tokenizer.save_pretrained(RERANK_MODEL_PATH)
                    self.reranker = CrossEncoder(RERANK_MODEL_PATH)
                    print(f"✓ Rerank模型下载完成: {RERANK_MODEL_PATH}")
                except Exception as e:
                    print(f"✗ Rerank模型加载失败: {e}")
                    USE_RERANK = False

        self._initialized = True

    # ---------------- 核心检索逻辑 ----------------

    def search_knowledge(self, query, top_k=5, allowed_levels=None, role=None, department=None, collections=None, source_filter=None):
        """
        混合检索逻辑封装

        Args:
            query: 查询文本
            top_k: 返回结果数量
            allowed_levels: 允许访问的安全级别列表
            role: 用户角色（多向量库模式）
            department: 用户部门（多向量库模式）
            collections: 指定查询的向量库列表
            source_filter: 文件名过滤，精确匹配（如 "2604.09205v1.pdf"）
        """
        if not self._initialized:
            self.initialize()

        if USE_MULTI_KB and self.kb_manager:
            return self._search_multi_kb(query, top_k, role, department, collections, source_filter=source_filter)

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

        query_kwargs = {
            "query_embeddings": [query_vector],
            "n_results": recall_k
        }
        if where_filter:
            query_kwargs["where"] = where_filter

        vector_results = self.collection.query(**query_kwargs)

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

        if USE_RERANK and self.reranker:
            fused_results = self.rerank_results(query, fused_results, top_k)
        else:
            fused_results = self._truncate_results(fused_results, top_k)

        return fused_results

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
        recall_k = RERANK_CANDIDATES if (USE_RERANK or USE_HYBRID_SEARCH) else top_k

        # 构建 where 过滤条件
        where_filter = None
        if source_filter:
            where_filter = {"source": source_filter}

        all_results = []
        for coll_name in target_collections:
            try:
                coll = self.kb_manager.get_collection(coll_name)
                if not coll: continue

                # 使用 where 过滤
                query_kwargs = {
                    "query_embeddings": [query_vector],
                    "n_results": recall_k
                }
                if where_filter:
                    query_kwargs["where"] = where_filter

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

        if not all_results:
            return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

        if len(all_results) == 1:
            fused_results = all_results[0]
        else:
            weights = [VECTOR_WEIGHT if i % 2 == 0 else BM25_WEIGHT for i in range(len(all_results))]
            fused_results = self.reciprocal_rank_fusion(all_results, weights)

        if USE_RERANK and self.reranker:
            fused_results = self.rerank_results(query, fused_results, top_k)
        else:
            fused_results = self._truncate_results(fused_results, top_k)

        return fused_results

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


# 快捷访问单例
def get_engine() -> RAGEngine:
    engine = RAGEngine.get_instance()
    if not engine._initialized:
        engine.initialize()
    return engine
