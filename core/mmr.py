# -*- coding: utf-8 -*-
"""
MMR（Max Marginal Relevance）去重模块

功能：
- 平衡相关性和多样性
- 避免重复内容占据 top_k 结果
- 前置到 rerank 之前，减少 rerank 输入量

使用场景：
召回 100 个 → MMR 去重取 30 个 → rerank 取 top_k
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """计算两个向量的余弦相似度"""
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(vec1, vec2) / (norm1 * norm2))


def mmr_rerank(
    query_emb: np.ndarray,
    candidates: List[Dict],
    top_k: int = 30,
    lambda_param: float = 0.5,
    emb_key: str = 'embedding'
) -> List[Dict]:
    """
    Max Marginal Relevance 去重

    公式: MMR = λ * Relevance - (1-λ) * Max_Similarity

    Args:
        query_emb: 查询向量
        candidates: 候选文档列表，每个文档需包含 embedding
        top_k: 返回数量
        lambda_param: 相关性/多样性权衡参数 (0-1)
            - 1.0: 只考虑相关性
            - 0.5: 平衡相关性和多样性
            - 0.0: 只考虑多样性
        emb_key: embedding 在候选文档中的 key

    Returns:
        去重后的候选文档列表
    """
    if not candidates:
        return []

    if len(candidates) <= top_k:
        return candidates

    selected = []
    remaining = candidates.copy()

    while len(selected) < top_k and remaining:
        mmr_scores = []

        for i, cand in enumerate(remaining):
            # 获取候选文档的 embedding
            cand_emb = cand.get(emb_key)
            if cand_emb is None:
                # 没有 embedding，跳过或使用默认分数
                mmr_scores.append(-float('inf'))
                continue

            cand_emb = np.array(cand_emb)

            # 1. 相关性：与查询的相似度
            relevance = cosine_similarity(query_emb, cand_emb)

            # 2. 冗余度：与已选文档的最大相似度
            if selected:
                # 过滤出有 embedding 的已选文档
                selected_with_emb = [s for s in selected if s.get(emb_key) is not None]
                if selected_with_emb:
                    max_sim = max(
                        cosine_similarity(cand_emb, np.array(s.get(emb_key)))
                        for s in selected_with_emb
                    )
                else:
                    max_sim = 0.0
            else:
                max_sim = 0.0

            # 3. MMR 分数 = λ * 相关性 - (1-λ) * 冗余度
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            mmr_scores.append(mmr_score)

        # 选择 MMR 分数最高的
        if mmr_scores:
            best_idx = np.argmax(mmr_scores)
            if mmr_scores[best_idx] > -float('inf'):
                selected.append(remaining.pop(best_idx))
            else:
                # 所有候选都没有 embedding，直接取前 top_k
                selected.extend(remaining[:top_k - len(selected)])
                break

    return selected


def mmr_filter_by_content(
    candidates: List[Dict],
    top_k: int = 30,
    similarity_threshold: float = 0.9
) -> List[Dict]:
    """
    基于内容相似度的去重（简化版，不需要 embedding）

    适用于：
    - 没有 embedding 的情况
    - 快速去重场景

    Args:
        candidates: 候选文档列表
        top_k: 返回数量
        similarity_threshold: 相似度阈值，超过则视为重复

    Returns:
        去重后的候选文档列表
    """
    if not candidates:
        return []

    if len(candidates) <= top_k:
        return candidates

    selected = []
    remaining = candidates.copy()

    while len(selected) < top_k and remaining:
        current = remaining.pop(0)

        # 检查是否与已选内容重复
        is_duplicate = False
        current_content = current.get('content', current.get('document', ''))[:200]

        for s in selected:
            s_content = s.get('content', s.get('document', ''))[:200]

            # 简单的 Jaccard 相似度
            words1 = set(current_content)
            words2 = set(s_content)
            if words1 and words2:
                intersection = len(words1 & words2)
                union = len(words1 | words2)
                similarity = intersection / union if union > 0 else 0

                if similarity > similarity_threshold:
                    is_duplicate = True
                    break

        if not is_duplicate:
            selected.append(current)

    return selected


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("MMR 去重测试")
    print("=" * 60)

    # 模拟候选文档
    np.random.seed(42)

    def random_embedding():
        emb = np.random.randn(768)
        return emb / np.linalg.norm(emb)

    query_emb = random_embedding()

    # 创建 10 个候选，前 5 个相似
    base_emb = random_embedding()
    candidates = []

    for i in range(10):
        if i < 5:
            # 前 5 个与 query 相似
            emb = query_emb + np.random.randn(768) * 0.1
        else:
            # 后 5 个与 query 不太相似
            emb = random_embedding()

        candidates.append({
            'id': f'doc_{i}',
            'content': f'文档内容 {i}',
            'embedding': emb / np.linalg.norm(emb)
        })

    print(f"\n候选数量: {len(candidates)}")

    # MMR 去重
    selected = mmr_rerank(query_emb, candidates, top_k=5, lambda_param=0.5)

    print(f"MMR 选择数量: {len(selected)}")
    print(f"选择的文档 ID: {[c['id'] for c in selected]}")

    # 计算多样性
    embs = [c['embedding'] for c in selected]
    diversity_scores = []
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            sim = cosine_similarity(embs[i], embs[j])
            diversity_scores.append(sim)

    avg_similarity = np.mean(diversity_scores) if diversity_scores else 0
    print(f"平均相似度（越低多样性越高）: {avg_similarity:.3f}")
