"""
置信度门控模块

基于 Reranker 分数判断检索结果质量，低于阈值则拦截并触发补救流程。

核心功能：
1. 使用 Reranker 计算检索结果的置信度分数
2. 根据阈值判断结果质量
3. 决定是继续生成还是触发补救流程

使用方式：
    from core.confidence_gate import ConfidenceGate, create_gate

    gate = create_gate()
    result = gate.evaluate(query, documents)

    if result.action == GateAction.REWRITE:
        # 触发查询重写或网络搜索
        ...
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


class GateAction(Enum):
    """门控动作"""
    PASS = "pass"                    # 通过，继续生成
    REWRITE = "rewrite"              # 需要查询重写
    WEB_SEARCH = "web_search"        # 触发网络搜索
    FALLBACK = "fallback"            # 降级处理（无结果）


@dataclass
class GateResult:
    """门控结果"""
    action: GateAction
    confidence: float          # 综合置信度
    top_score: float          # Top-1 分数
    avg_score: float          # Top-3 平均分数
    reason: str               # 决策原因
    suggested_action: str     # 建议的后续动作
    scores: List[float] = None  # 所有分数


class ConfidenceGate:
    """
    置信度门控器

    基于 Reranker 分数判断检索结果质量，决定是否继续生成或触发补救。

    阈值设计（基于 Agentic RAG 优化报告）：
    - PASS_THRESHOLD = 0.35: 通过阈值，低于此值需要补救
    - GOOD_THRESHOLD = 0.5: 良好阈值，高质量结果
    - EXCELLENT_THRESHOLD = 0.7: 优秀阈值，可直接生成
    """

    # 关键阈值
    # 2026-04-15: PASS_THRESHOLD 从 0.35 降低到 0.2，减少误判导致补救流程
    PASS_THRESHOLD = 0.2      # 通过阈值（降低以减少误判）
    GOOD_THRESHOLD = 0.4      # 良好阈值（从 0.5 降低）
    EXCELLENT_THRESHOLD = 0.7 # 优秀阈值

    def __init__(self, reranker=None):
        """
        初始化门控器

        Args:
            reranker: CrossEncoder 重排序模型
        """
        self.reranker = reranker

    def evaluate(self, query: str, documents: List[str],
                 metadatas: List[dict] = None) -> GateResult:
        """
        评估检索结果质量

        Args:
            query: 用户查询
            documents: 检索到的文档列表
            metadatas: 文档元数据（可选，用于更精确评估）

        Returns:
            GateResult: 门控决策结果
        """
        # 无结果情况
        if not documents:
            return GateResult(
                action=GateAction.FALLBACK,
                confidence=0.0,
                top_score=0.0,
                avg_score=0.0,
                reason="无检索结果",
                suggested_action="尝试网络搜索或告知用户无相关信息"
            )

        # 使用 Reranker 计算置信度分数
        scores = self._compute_scores(query, documents)

        top_score = max(scores) if scores else 0.0
        avg_score = sum(scores[:3]) / min(3, len(scores)) if len(scores) >= 1 else 0.0

        # 决策逻辑
        if top_score >= self.GOOD_THRESHOLD:
            # 高置信度，直接通过
            return GateResult(
                action=GateAction.PASS,
                confidence=top_score,
                top_score=top_score,
                avg_score=avg_score,
                reason=f"检索结果置信度高 ({top_score:.3f} >= {self.GOOD_THRESHOLD})，可直接生成回答",
                suggested_action="继续生成答案",
                scores=scores
            )

        elif top_score >= self.PASS_THRESHOLD:
            # 中等置信度，可以通过但建议关注
            return GateResult(
                action=GateAction.PASS,
                confidence=top_score,
                top_score=top_score,
                avg_score=avg_score,
                reason=f"检索结果置信度中等 ({top_score:.3f})，可能需要补充信息",
                suggested_action="继续生成答案，但需标注不确定性",
                scores=scores
            )

        else:
            # 低置信度，需要补救
            # 判断是触发查询重写还是网络搜索
            if avg_score < self.PASS_THRESHOLD:
                # 平均分也很低，直接网络搜索
                return GateResult(
                    action=GateAction.WEB_SEARCH,
                    confidence=top_score,
                    top_score=top_score,
                    avg_score=avg_score,
                    reason=f"Top-1 置信度 {top_score:.3f} 低于阈值 {self.PASS_THRESHOLD}，平均置信度 {avg_score:.3f} 也很低",
                    suggested_action="触发网络搜索作为补充",
                    scores=scores
                )
            else:
                # 尝试查询重写
                return GateResult(
                    action=GateAction.REWRITE,
                    confidence=top_score,
                    top_score=top_score,
                    avg_score=avg_score,
                    reason=f"Top-1 置信度 {top_score:.3f} 低于阈值 {self.PASS_THRESHOLD}，尝试查询重写",
                    suggested_action="触发查询重写或补充检索",
                    scores=scores
                )

    def _compute_scores(self, query: str, documents: List[str]) -> List[float]:
        """
        计算 Reranker 分数

        Args:
            query: 用户查询
            documents: 文档列表

        Returns:
            分数列表
        """
        if not self.reranker:
            # 无 Reranker，使用简单关键词匹配降级
            return self._keyword_fallback(query, documents)

        try:
            import numpy as np
            pairs = [(query, doc) for doc in documents]
            scores = self.reranker.predict(pairs)
            # 确保返回 float 列表
            return [float(s) for s in scores]
        except Exception as e:
            print(f"[警告] Reranker 计算失败: {e}")
            return self._keyword_fallback(query, documents)

    def _keyword_fallback(self, query: str, documents: List[str]) -> List[float]:
        """
        关键词匹配降级方案

        当 Reranker 不可用时，使用关键词匹配作为降级方案。
        返回归一化到 0-1 范围的分数。
        """
        try:
            import jieba
        except ImportError:
            # jieba 不可用，返回中等分数
            return [0.5] * len(documents)

        # 提取查询关键词
        query_words = set()
        for word in jieba.cut(query):
            word = word.strip()
            if len(word) >= 2:
                query_words.add(word.lower())

        if not query_words:
            return [0.5] * len(documents)

        scores = []
        for doc in documents:
            doc_lower = doc.lower()
            matched = sum(1 for word in query_words if word in doc_lower)
            # 归一化到 0-1
            score = matched / len(query_words)
            # 映射到类似 Reranker 的范围（关键词匹配通常分数较低，需要放大）
            score = min(score * 0.8, 1.0)
            scores.append(score)

        return scores

    def get_threshold_info(self) -> dict:
        """获取阈值信息"""
        return {
            "pass_threshold": self.PASS_THRESHOLD,
            "good_threshold": self.GOOD_THRESHOLD,
            "excellent_threshold": self.EXCELLENT_THRESHOLD,
            "has_reranker": self.reranker is not None
        }


def create_gate() -> ConfidenceGate:
    """
    创建门控器实例

    自动从 RAG Engine 获取 Reranker 模型。

    Returns:
        ConfidenceGate: 门控器实例
    """
    try:
        from core.engine import get_engine
        engine = get_engine()
        return ConfidenceGate(reranker=engine.reranker)
    except Exception as e:
        print(f"[警告] 创建门控器失败，使用降级模式: {e}")
        return ConfidenceGate(reranker=None)


# ==================== 便捷函数 ====================

def check_confidence(query: str, documents: List[str]) -> GateResult:
    """
    便捷函数：检查检索结果置信度

    Args:
        query: 用户查询
        documents: 检索到的文档列表

    Returns:
        GateResult: 门控决策结果
    """
    gate = create_gate()
    return gate.evaluate(query, documents)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("置信度门控测试")
    print("=" * 60)

    # 测试用例
    test_cases = [
        # (query, documents, expected_action)
        (
            "公司报销制度是怎样的？",
            ["报销制度规定员工可以报销差旅费用，需提供发票...", "根据公司规定，报销需在30天内提交..."],
            GateAction.PASS  # 应该高分通过
        ),
        (
            "宇宙的终极答案是什么？",
            ["文档中提到了一些技术细节...", "另一个不相关的内容..."],
            GateAction.REWRITE  # 低置信度，需要补救
        ),
        (
            "测试空结果",
            [],
            GateAction.FALLBACK  # 无结果
        ),
    ]

    gate = ConfidenceGate()  # 不使用 Reranker 的测试

    print(f"\n阈值配置: {gate.get_threshold_info()}")
    print()

    for i, (query, docs, expected) in enumerate(test_cases, 1):
        result = gate.evaluate(query, docs)
        status = "[OK]" if result.action == expected else "[WARN]"
        print(f"测试 {i}: {status}")
        print(f"  查询: {query}")
        print(f"  文档数: {len(docs)}")
        print(f"  动作: {result.action.value}")
        print(f"  置信度: {result.confidence:.3f}")
        print(f"  Top分数: {result.top_score:.3f}")
        print(f"  原因: {result.reason}")
        print()
