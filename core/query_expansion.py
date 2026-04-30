# -*- coding: utf-8 -*-
"""
Query Expansion 模块（安全版）

功能：
- 查询扩展：扩展查询词，提升召回率
- 安全过滤：扩展词必须与原查询相似度 > threshold
- 防止噪声词污染检索

使用方式：
    from core.query_expansion import expand_query_safe, expand_query_data_driven

    # 方案A：相似度过滤
    expansions = expand_query_safe(query, threshold=0.8)

    # 方案B：数据驱动扩展
    expansions = expand_query_data_driven(query, vector_store)
"""

import logging
from typing import List, Dict, Optional, Set
import numpy as np

logger = logging.getLogger(__name__)


# ==================== 领域术语词典 ====================
# 可根据实际业务扩展

DOMAIN_TERMS = {
    # 报销相关
    "报销": ["差旅报销", "费用报销", "报销审批", "报销标准", "报销流程"],
    "出差": ["差旅", "出差申请", "出差审批", "差旅费"],
    "请假": ["休假申请", "请假审批", "年假", "事假", "病假"],

    # 人事相关
    "入职": ["入职办理", "新员工", "入职流程", "试用期"],
    "离职": ["离职办理", "辞职", "离职流程", "离职审批"],
    "薪资": ["工资", "薪酬", "薪资结构", "绩效考核"],

    # 通用
    "流程": ["办理流程", "操作流程", "审批流程"],
    "标准": ["标准规范", "规定", "制度"],
    "申请": ["申请流程", "申请条件", "申请材料"],
}


def get_domain_terms(query: str) -> List[str]:
    """
    从领域词典获取扩展词

    Args:
        query: 用户查询

    Returns:
        扩展词列表
    """
    expansions = []

    for keyword, terms in DOMAIN_TERMS.items():
        if keyword in query:
            expansions.extend(terms)

    return expansions


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """计算余弦相似度"""
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(vec1, vec2) / (norm1 * norm2))


def expand_query_safe(
    query: str,
    embedding_model=None,
    threshold: float = 0.8,
    max_expansions: int = 5
) -> List[str]:
    """
    安全的查询扩展（带相似度过滤）

    Args:
        query: 用户查询
        embedding_model: embedding 模型（用于计算相似度）
        threshold: 相似度阈值，扩展词必须 > threshold
        max_expansions: 最大扩展数量

    Returns:
        扩展后的查询列表（包含原查询）
    """
    expansions = [query]

    # 1. 从领域词典获取候选扩展词
    domain_candidates = get_domain_terms(query)

    if not domain_candidates:
        return expansions

    # 2. 如果没有 embedding 模型，直接返回领域词（但限制数量）
    if embedding_model is None:
        # 没有 embedding，只取前几个
        expansions.extend(domain_candidates[:max_expansions])
        return list(set(expansions))

    # 3. 有 embedding 模型，做相似度过滤
    try:
        query_emb = embedding_model.encode(query)

        scored_candidates = []
        for candidate in domain_candidates:
            cand_emb = embedding_model.encode(candidate)
            similarity = cosine_similarity(query_emb, cand_emb)

            if similarity > threshold:
                scored_candidates.append((candidate, similarity))

        # 按相似度排序，取前 max_expansions
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        filtered = [c[0] for c in scored_candidates[:max_expansions]]

        expansions.extend(filtered)

    except Exception as e:
        logger.warning(f"Query expansion embedding 计算失败: {e}")
        # 降级：直接使用领域词
        expansions.extend(domain_candidates[:max_expansions])

    return list(set(expansions))


def expand_query_data_driven(
    query: str,
    search_func=None,
    top_k: int = 3
) -> List[str]:
    """
    数据驱动的查询扩展

    从向量库中查找相似查询，而非使用规则词典

    Args:
        query: 用户查询
        search_func: 向量检索函数
        top_k: 扩展数量

    Returns:
        扩展后的查询列表
    """
    expansions = [query]

    if search_func is None:
        return expansions

    try:
        # 在向量库中搜索相似文档
        # 取文档的前几个关键词作为扩展
        results = search_func(query, top_k=top_k)

        if results and results.get('documents') and results['documents'][0]:
            for doc in results['documents'][0][:top_k]:
                # 从文档中提取关键词
                keywords = extract_keywords(doc, top_n=2)
                expansions.extend(keywords)

    except Exception as e:
        logger.warning(f"数据驱动扩展失败: {e}")

    return list(set(expansions))


def extract_keywords(text: str, top_n: int = 3) -> List[str]:
    """
    从文本中提取关键词（简单实现）

    Args:
        text: 文本内容
        top_n: 提取数量

    Returns:
        关键词列表
    """
    try:
        import jieba
        import jieba.analyse

        keywords = jieba.analyse.extract_tags(text, topK=top_n)
        return keywords
    except ImportError:
        # 没有 jieba，简单分词
        words = text.split()[:top_n]
        return [w for w in words if len(w) > 1]


def merge_expansion_results(
    query: str,
    expansions: List[str],
    search_func,
    top_k_per_query: int = 3,
    final_top_k: int = 10
) -> List[Dict]:
    """
    合并多个扩展查询的检索结果

    Args:
        query: 原始查询
        expansions: 扩展查询列表
        search_func: 检索函数
        top_k_per_query: 每个查询返回数量
        final_top_k: 最终返回数量

    Returns:
        合并后的结果列表
    """
    all_results = []
    seen_ids = set()

    for q in expansions:
        try:
            results = search_func(q, top_k=top_k_per_query)

            if results and results.get('ids') and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        all_results.append({
                            'id': doc_id,
                            'content': results['documents'][0][i] if results.get('documents') else '',
                            'metadata': results['metadatas'][0][i] if results.get('metadatas') else {},
                            'score': results['distances'][0][i] if results.get('distances') else 0,
                            'query': q
                        })
        except Exception as e:
            logger.warning(f"扩展查询检索失败: {q}, 错误: {e}")

    # 按分数排序
    all_results.sort(key=lambda x: x.get('score', 0), reverse=True)

    return all_results[:final_top_k]


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("Query Expansion 测试")
    print("=" * 60)

    # 测试领域词典扩展
    test_queries = [
        "报销标准是什么？",
        "出差流程怎么走？",
        "入职需要什么材料？"
    ]

    for query in test_queries:
        print(f"\n原查询: {query}")

        # 无 embedding 的扩展
        expansions = expand_query_safe(query, embedding_model=None, threshold=0.8)
        print(f"扩展词（无 embedding）: {expansions}")

        # 领域词
        domain_terms = get_domain_terms(query)
        print(f"领域词: {domain_terms}")
