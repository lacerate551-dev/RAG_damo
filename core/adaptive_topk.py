"""
自适应 TopK 策略

根据检索置信度动态调整 top_k：
- 低置信度：扩大检索范围
- 高置信度：缩小检索范围
- 中等置信度：保持原样

使用方式：
    from core.adaptive_topk import AdaptiveTopK

    strategy = AdaptiveTopK()
    adjusted_k, should_retrieve = strategy.adjust(top_score, initial_k)
"""

from dataclasses import dataclass
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveConfig:
    """自适应配置"""
    # 置信度阈值
    low_confidence_threshold: float = 0.5    # 低于此值认为是低置信度
    high_confidence_threshold: float = 0.8   # 高于此值认为是高置信度

    # 扩展/收缩比例
    expand_ratio: float = 2.0                # 低置信度时扩大倍数
    shrink_ratio: float = 0.5                # 高置信度时缩小比例

    # 限制
    min_top_k: int = 3                       # 最小 top_k
    max_top_k: int = 20                      # 最大 top_k

    # 是否启用
    enabled: bool = True


class AdaptiveTopK:
    """
    自适应 TopK 策略

    核心逻辑：
    1. 第一次检索返回结果后，检查最高得分
    2. 根据得分判断置信度
    3. 决定是否需要调整 top_k 重新检索
    """

    def __init__(self, config: AdaptiveConfig = None):
        """
        初始化

        Args:
            config: 配置对象，如果为None则使用默认配置
        """
        self.config = config or AdaptiveConfig()

    def adjust(
        self,
        top_score: float,
        initial_k: int,
        current_results_count: int = 0
    ) -> Tuple[int, bool, str]:
        """
        根据置信度调整 top_k

        Args:
            top_score: 当前检索结果的最高得分 (0-1)
            initial_k: 初始 top_k
            current_results_count: 当前结果数量

        Returns:
            (adjusted_k, should_retrieve, reason)
            - adjusted_k: 调整后的 top_k
            - should_retrieve: 是否需要重新检索
            - reason: 调整原因
        """
        if not self.config.enabled:
            return initial_k, False, "disabled"

        # 低置信度：扩大检索范围
        if top_score < self.config.low_confidence_threshold:
            adjusted_k = min(
                int(initial_k * self.config.expand_ratio),
                self.config.max_top_k
            )
            if adjusted_k > initial_k:
                return adjusted_k, True, f"low_confidence({top_score:.2f}<{self.config.low_confidence_threshold})"

        # 高置信度：可以缩小范围（但不重新检索）
        elif top_score > self.config.high_confidence_threshold:
            adjusted_k = max(
                int(initial_k * self.config.shrink_ratio),
                self.config.min_top_k
            )
            # 高置信度时不需要重新检索，只是返回时可以截断
            return adjusted_k, False, f"high_confidence({top_score:.2f}>{self.config.high_confidence_threshold})"

        # 中等置信度：保持原样
        return initial_k, False, f"medium_confidence({top_score:.2f})"

    def get_final_results(
        self,
        results: list,
        adjusted_k: int,
        reason: str
    ) -> list:
        """
        获取最终结果

        Args:
            results: 检索结果列表
            adjusted_k: 调整后的 top_k
            reason: 调整原因

        Returns:
            截断后的结果列表
        """
        if "high_confidence" in reason:
            # 高置信度时截断结果
            return results[:adjusted_k]
        return results

    def get_config_dict(self) -> dict:
        """获取配置字典"""
        return {
            "enabled": self.config.enabled,
            "low_confidence_threshold": self.config.low_confidence_threshold,
            "high_confidence_threshold": self.config.high_confidence_threshold,
            "expand_ratio": self.config.expand_ratio,
            "shrink_ratio": self.config.shrink_ratio,
            "min_top_k": self.config.min_top_k,
            "max_top_k": self.config.max_top_k
        }


class AdaptiveTopKWithStats(AdaptiveTopK):
    """
    带统计的自适应 TopK 策略

    记录每次调整的统计信息，用于分析和优化
    """

    def __init__(self, config: AdaptiveConfig = None):
        super().__init__(config)
        self.stats = {
            "total_queries": 0,
            "low_confidence_count": 0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "re_retrieve_count": 0
        }

    def adjust(
        self,
        top_score: float,
        initial_k: int,
        current_results_count: int = 0
    ) -> Tuple[int, bool, str]:
        """带统计的调整"""
        self.stats["total_queries"] += 1

        adjusted_k, should_retrieve, reason = super().adjust(
            top_score, initial_k, current_results_count
        )

        # 更新统计
        if "low_confidence" in reason:
            self.stats["low_confidence_count"] += 1
        elif "high_confidence" in reason:
            self.stats["high_confidence_count"] += 1
        else:
            self.stats["medium_confidence_count"] += 1

        if should_retrieve:
            self.stats["re_retrieve_count"] += 1

        return adjusted_k, should_retrieve, reason

    def get_stats(self) -> dict:
        """获取统计信息"""
        return self.stats.copy()

    def reset_stats(self):
        """重置统计"""
        self.stats = {
            "total_queries": 0,
            "low_confidence_count": 0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "re_retrieve_count": 0
        }


# ==================== 便捷函数 ====================

def create_adaptive_topk(
    enabled: bool = True,
    low_threshold: float = 0.5,
    high_threshold: float = 0.8,
    expand_ratio: float = 2.0,
    shrink_ratio: float = 0.5
) -> AdaptiveTopK:
    """
    创建自适应 TopK 策略

    Args:
        enabled: 是否启用
        low_threshold: 低置信度阈值
        high_threshold: 高置信度阈值
        expand_ratio: 扩展比例
        shrink_ratio: 收缩比例

    Returns:
        AdaptiveTopK 实例
    """
    config = AdaptiveConfig(
        enabled=enabled,
        low_confidence_threshold=low_threshold,
        high_confidence_threshold=high_threshold,
        expand_ratio=expand_ratio,
        shrink_ratio=shrink_ratio
    )
    return AdaptiveTopK(config)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("自适应 TopK 策略测试")
    print("=" * 60)

    strategy = AdaptiveTopKWithStats()

    test_cases = [
        (0.3, 5, "低置信度 - 应该扩展"),
        (0.6, 5, "中等置信度 - 保持"),
        (0.9, 5, "高置信度 - 应该收缩"),
        (0.45, 10, "边界低置信度"),
        (0.8, 10, "边界高置信度"),
    ]

    for top_score, initial_k, description in test_cases:
        adjusted_k, should_retrieve, reason = strategy.adjust(top_score, initial_k)
        print(f"\n{description}")
        print(f"  输入: top_score={top_score}, initial_k={initial_k}")
        print(f"  输出: adjusted_k={adjusted_k}, should_retrieve={should_retrieve}")
        print(f"  原因: {reason}")

    print("\n" + "=" * 60)
    print("统计信息:")
    stats = strategy.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
