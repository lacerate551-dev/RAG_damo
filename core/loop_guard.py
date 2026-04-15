"""
循环检索防护模块

防止 Agentic RAG 陷入无限检索循环，确保检索效率和质量。

核心机制：
1. 最大迭代数限制（max_iterations=3）
2. 置信度递增检查（每次迭代置信度必须提升）
3. 重复查询检测（避免重复检索相同内容）
4. 循环中断决策（判断是否应该停止迭代）

使用方式：
    from core.loop_guard import LoopGuard, GuardDecision

    guard = LoopGuard(max_iterations=3)
    guard.record_iteration(query, confidence, results_count)

    decision = guard.should_continue()
    if decision == GuardDecision.STOP:
        # 终止迭代
        ...
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
import time


class GuardDecision(Enum):
    """循环防护决策"""
    CONTINUE = "continue"       # 继续迭代
    STOP_MAX_ITER = "stop_max_iter"  # 达到最大迭代数
    STOP_NO_PROGRESS = "stop_no_progress"  # 无进展（置信度未提升）
    STOP_DUPLICATE = "stop_duplicate"  # 重复查询
    STOP_SUFFICIENT = "stop_sufficient"  # 结果已足够


@dataclass
class IterationRecord:
    """迭代记录"""
    iteration: int              # 迭代次数
    query: str                  # 查询内容
    confidence: float           # 置信度分数
    results_count: int          # 检索结果数量
    timestamp: float            # 时间戳
    query_type: str             # 查询类型（可选）


@dataclass
class GuardResult:
    """防护检查结果"""
    decision: GuardDecision     # 决策
    reason: str                 # 原因
    current_iteration: int      # 当前迭代次数
    confidence_trend: str       # 置信度趋势（"improving"/"stable"/"declining"）
    recommendation: str         # 建议


class LoopGuard:
    """
    循环检索防护器

    监控迭代过程，防止无限循环和无效迭代。
    """

    # 默认参数
    DEFAULT_MAX_ITERATIONS = 3
    MIN_CONFIDENCE_IMPROVEMENT = 0.05  # 最小置信度提升阈值

    def __init__(self, max_iterations: int = None,
                 min_confidence_improvement: float = None):
        """
        初始化防护器

        Args:
            max_iterations: 最大迭代次数
            min_confidence_improvement: 最小置信度提升阈值
        """
        self.max_iterations = max_iterations or self.DEFAULT_MAX_ITERATIONS
        self.min_confidence_improvement = min_confidence_improvement or self.MIN_CONFIDENCE_IMPROVEMENT

        # 迭代历史
        self.iterations: List[IterationRecord] = []
        self.query_history: List[str] = []

    def record_iteration(self, query: str, confidence: float,
                        results_count: int, query_type: str = None) -> IterationRecord:
        """
        记录一次迭代

        Args:
            query: 查询内容
            confidence: 置信度分数
            results_count: 检索结果数量
            query_type: 查询类型

        Returns:
            IterationRecord: 迭代记录
        """
        record = IterationRecord(
            iteration=len(self.iterations) + 1,
            query=query,
            confidence=confidence,
            results_count=results_count,
            timestamp=time.time(),
            query_type=query_type
        )

        self.iterations.append(record)
        self.query_history.append(query.lower().strip())

        return record

    def should_continue(self, current_confidence: float = None) -> GuardResult:
        """
        判断是否应该继续迭代

        Args:
            current_confidence: 当前置信度（可选，使用最近记录）

        Returns:
            GuardResult: 防护检查结果
        """
        # 检查最大迭代数
        if len(self.iterations) >= self.max_iterations:
            return GuardResult(
                decision=GuardDecision.STOP_MAX_ITER,
                reason=f"已达到最大迭代次数 {self.max_iterations}",
                current_iteration=len(self.iterations),
                confidence_trend=self._get_confidence_trend(),
                recommendation="使用当前结果生成答案"
            )

        # 检查是否有记录
        if not self.iterations:
            return GuardResult(
                decision=GuardDecision.CONTINUE,
                reason="首次迭代",
                current_iteration=0,
                confidence_trend="unknown",
                recommendation="继续执行首次检索"
            )

        # 获取当前置信度
        if current_confidence is None:
            current_confidence = self.iterations[-1].confidence

        # 检查置信度是否足够高
        if current_confidence >= 0.7:  # 高置信度阈值
            return GuardResult(
                decision=GuardDecision.STOP_SUFFICIENT,
                reason=f"置信度已足够高 ({current_confidence:.3f})",
                current_iteration=len(self.iterations),
                confidence_trend="good",
                recommendation="结果质量良好，可以生成答案"
            )

        # 检查置信度趋势
        trend = self._get_confidence_trend()

        if trend == "declining":
            return GuardResult(
                decision=GuardDecision.STOP_NO_PROGRESS,
                reason="置信度下降，继续迭代无益",
                current_iteration=len(self.iterations),
                confidence_trend=trend,
                recommendation="停止迭代，使用最佳历史结果"
            )

        if trend == "stable" and len(self.iterations) >= 2:
            # 检查是否有显著提升
            recent_improvement = self._get_recent_improvement()
            if recent_improvement < self.min_confidence_improvement:
                return GuardResult(
                    decision=GuardDecision.STOP_NO_PROGRESS,
                    reason=f"置信度提升不明显 ({recent_improvement:.3f} < {self.min_confidence_improvement})",
                    current_iteration=len(self.iterations),
                    confidence_trend=trend,
                    recommendation="检索结果趋于稳定，停止迭代"
                )

        return GuardResult(
            decision=GuardDecision.CONTINUE,
            reason="迭代正常进行中",
            current_iteration=len(self.iterations),
            confidence_trend=trend,
            recommendation="继续执行下一次检索"
        )

    def is_duplicate_query(self, query: str, similarity_threshold: float = 0.9) -> bool:
        """
        检测是否为重复查询

        Args:
            query: 待检测查询
            similarity_threshold: 相似度阈值

        Returns:
            bool: 是否为重复查询
        """
        query_lower = query.lower().strip()

        # 完全匹配
        if query_lower in self.query_history:
            return True

        # 简单相似度检查（基于共同词比例）
        try:
            import jieba
            query_words = set(w for w in jieba.cut(query_lower) if len(w) >= 2)

            for hist_query in self.query_history:
                hist_words = set(w for w in jieba.cut(hist_query) if len(w) >= 2)
                if not query_words or not hist_words:
                    continue

                intersection = len(query_words & hist_words)
                union = len(query_words | hist_words)
                similarity = intersection / union if union > 0 else 0

                if similarity >= similarity_threshold:
                    return True
        except ImportError:
            pass

        return False

    def get_best_iteration(self) -> Optional[IterationRecord]:
        """获取最佳迭代记录（置信度最高）"""
        if not self.iterations:
            return None
        return max(self.iterations, key=lambda r: r.confidence)

    def get_summary(self) -> dict:
        """获取迭代摘要"""
        if not self.iterations:
            return {
                "total_iterations": 0,
                "best_confidence": 0,
                "avg_confidence": 0,
                "total_results": 0
            }

        confidences = [r.confidence for r in self.iterations]
        return {
            "total_iterations": len(self.iterations),
            "best_confidence": max(confidences),
            "avg_confidence": sum(confidences) / len(confidences),
            "total_results": sum(r.results_count for r in self.iterations),
            "confidence_trend": self._get_confidence_trend(),
            "iterations": [
                {
                    "iteration": r.iteration,
                    "confidence": r.confidence,
                    "results_count": r.results_count
                }
                for r in self.iterations
            ]
        }

    def _get_confidence_trend(self) -> str:
        """获取置信度趋势"""
        if len(self.iterations) < 2:
            return "unknown"

        confidences = [r.confidence for r in self.iterations]

        # 计算趋势
        improving_count = 0
        declining_count = 0

        for i in range(1, len(confidences)):
            diff = confidences[i] - confidences[i-1]
            if diff > 0.02:
                improving_count += 1
            elif diff < -0.02:
                declining_count += 1

        if declining_count > improving_count:
            return "declining"
        elif improving_count > declining_count:
            return "improving"
        else:
            return "stable"

    def _get_recent_improvement(self) -> float:
        """获取最近的置信度提升"""
        if len(self.iterations) < 2:
            return 0.0

        return self.iterations[-1].confidence - self.iterations[-2].confidence

    def reset(self):
        """重置防护器状态"""
        self.iterations.clear()
        self.query_history.clear()

    def get_config(self) -> dict:
        """获取配置信息"""
        return {
            "max_iterations": self.max_iterations,
            "min_confidence_improvement": self.min_confidence_improvement
        }


def create_guard(max_iterations: int = 3) -> LoopGuard:
    """
    创建循环防护器实例

    Args:
        max_iterations: 最大迭代次数

    Returns:
        LoopGuard: 防护器实例
    """
    return LoopGuard(max_iterations=max_iterations)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("循环检索防护测试")
    print("=" * 60)

    guard = LoopGuard(max_iterations=3)

    print(f"\n配置: {guard.get_config()}")

    # 模拟迭代
    test_iterations = [
        ("公司报销制度", 0.3, 5),
        ("报销流程规定", 0.45, 8),
        ("报销审批标准", 0.42, 6),  # 置信度下降
    ]

    print("\n模拟迭代过程:")
    for query, confidence, count in test_iterations:
        # 检查重复
        is_dup = guard.is_duplicate_query(query)
        if is_dup:
            print(f"  ⚠️ 检测到重复查询: {query}")

        # 记录迭代
        guard.record_iteration(query, confidence, count)

        # 检查是否继续
        result = guard.should_continue()

        print(f"  迭代 {result.current_iteration}: {query}")
        print(f"    置信度: {confidence:.3f}, 趋势: {result.confidence_trend}")
        print(f"    决策: {result.decision.value}")
        print(f"    原因: {result.reason}")

        if result.decision != GuardDecision.CONTINUE:
            print(f"    🛑 停止迭代")
            break

    print(f"\n迭代摘要:")
    summary = guard.get_summary()
    print(f"  总迭代数: {summary['total_iterations']}")
    print(f"  最佳置信度: {summary['best_confidence']:.3f}")
    print(f"  平均置信度: {summary['avg_confidence']:.3f}")
    print(f"  总结果数: {summary['total_results']}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)
