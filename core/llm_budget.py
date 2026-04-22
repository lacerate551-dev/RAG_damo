# -*- coding: utf-8 -*-
"""
LLM 调用预算控制器

控制每次查询的 LLM 调用次数，防止过度消耗

功能：
- 每次查询最大调用次数限制
- 特定类型调用次数限制（如重写、反思）
- 调用统计与监控
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum
import time
import threading
import logging

logger = logging.getLogger(__name__)


class CallType(Enum):
    """LLM 调用类型"""
    CLASSIFY = "classify"      # 查询分类
    REWRITE = "rewrite"        # 查询重写
    GENERATE = "generate"      # 答案生成
    REFLECT = "reflect"        # 推理反思
    DECOMPOSE = "decompose"    # 查询分解
    WEB_SEARCH = "web_search"  # 网络搜索
    GRAPH = "graph"            # 图谱检索


@dataclass
class CallRecord:
    """调用记录"""
    call_type: CallType
    timestamp: float
    tokens_used: int = 0
    success: bool = True
    description: str = ""


@dataclass
class BudgetConfig:
    """预算配置"""
    max_calls_per_query: int = 2      # 每次查询最大调用次数
    max_tokens_per_query: int = 8000  # 每次查询最大 token 数
    max_rewrites: int = 1             # 最多重写次数
    max_reflects: int = 1             # 最多反思次数
    max_decomposes: int = 1           # 最多分解次数


class LLMBudgetController:
    """LLM 调用预算控制器"""

    DEFAULT_CONFIG = BudgetConfig()

    def __init__(self, config: BudgetConfig = None):
        self.config = config or self.DEFAULT_CONFIG
        self._current_query_calls: List[CallRecord] = []
        self._lock = threading.Lock()
        self._total_stats = {
            "total_queries": 0,
            "total_calls": 0,
            "total_tokens": 0,
            "budget_exceeded": 0
        }

    def start_query(self) -> None:
        """开始新查询（重置计数）"""
        with self._lock:
            self._current_query_calls.clear()

    def can_call(self, call_type: CallType) -> bool:
        """
        检查是否可以进行指定类型的调用

        Args:
            call_type: 调用类型

        Returns:
            是否允许调用
        """
        with self._lock:
            # 检查总调用次数
            if len(self._current_query_calls) >= self.config.max_calls_per_query:
                logger.debug(f"LLM 预算超限: 已调用 {len(self._current_query_calls)} 次")
                return False

            # 检查特定类型限制
            type_count = sum(
                1 for c in self._current_query_calls
                if c.call_type == call_type
            )

            if call_type == CallType.REWRITE and type_count >= self.config.max_rewrites:
                logger.debug(f"重写次数超限: 已重写 {type_count} 次")
                return False

            if call_type == CallType.REFLECT and type_count >= self.config.max_reflects:
                logger.debug(f"反思次数超限: 已反思 {type_count} 次")
                return False

            if call_type == CallType.DECOMPOSE and type_count >= self.config.max_decomposes:
                logger.debug(f"分解次数超限: 已分解 {type_count} 次")
                return False

            return True

    def record_call(self, call_type: CallType, tokens_used: int = 0,
                    success: bool = True, description: str = "") -> CallRecord:
        """
        记录一次调用

        Args:
            call_type: 调用类型
            tokens_used: 使用的 token 数
            success: 是否成功
            description: 调用描述

        Returns:
            调用记录
        """
        record = CallRecord(
            call_type=call_type,
            timestamp=time.time(),
            tokens_used=tokens_used,
            success=success,
            description=description
        )

        with self._lock:
            self._current_query_calls.append(record)
            self._total_stats["total_calls"] += 1
            self._total_stats["total_tokens"] += tokens_used

        return record

    def end_query(self) -> Dict:
        """
        结束当前查询，返回统计信息

        Returns:
            本次查询的统计信息
        """
        with self._lock:
            stats = {
                "calls": len(self._current_query_calls),
                "tokens": sum(c.tokens_used for c in self._current_query_calls),
                "call_types": {}
            }

            for call in self._current_query_calls:
                type_name = call.call_type.value
                stats["call_types"][type_name] = stats["call_types"].get(type_name, 0) + 1

            if stats["calls"] >= self.config.max_calls_per_query:
                self._total_stats["budget_exceeded"] += 1

            self._total_stats["total_queries"] += 1
            self._current_query_calls.clear()

            return stats

    def get_current_stats(self) -> Dict:
        """获取当前查询的调用统计"""
        with self._lock:
            return {
                "total_calls": len(self._current_query_calls),
                "max_calls": self.config.max_calls_per_query,
                "remaining_calls": self.config.max_calls_per_query - len(self._current_query_calls),
                "tokens_used": sum(c.tokens_used for c in self._current_query_calls),
                "call_types": {
                    call.call_type.value: sum(1 for c in self._current_query_calls if c.call_type == call)
                    for call in CallType
                }
            }

    def get_total_stats(self) -> Dict:
        """获取总体统计信息"""
        with self._lock:
            return {
                **self._total_stats,
                "avg_calls_per_query": (
                    self._total_stats["total_calls"] / self._total_stats["total_queries"]
                    if self._total_stats["total_queries"] > 0 else 0
                ),
                "avg_tokens_per_query": (
                    self._total_stats["total_tokens"] / self._total_stats["total_queries"]
                    if self._total_stats["total_queries"] > 0 else 0
                )
            }

    def reset_stats(self) -> None:
        """重置统计信息"""
        with self._lock:
            self._total_stats = {
                "total_queries": 0,
                "total_calls": 0,
                "total_tokens": 0,
                "budget_exceeded": 0
            }


# ==================== 全局预算控制器 ====================

_budget_controller: Optional[LLMBudgetController] = None
_budget_lock = threading.Lock()


def get_budget_controller() -> LLMBudgetController:
    """获取全局预算控制器实例（单例模式）"""
    global _budget_controller
    if _budget_controller is None:
        with _budget_lock:
            if _budget_controller is None:
                # 尝试从配置加载参数
                try:
                    from config import MAX_LLM_CALLS_PER_QUERY, MAX_QUERY_REWRITES
                    config = BudgetConfig(
                        max_calls_per_query=MAX_LLM_CALLS_PER_QUERY,
                        max_rewrites=MAX_QUERY_REWRITES
                    )
                    _budget_controller = LLMBudgetController(config)
                except ImportError:
                    _budget_controller = LLMBudgetController()
    return _budget_controller


def reset_budget_controller() -> None:
    """重置全局预算控制器（主要用于测试）"""
    global _budget_controller
    with _budget_lock:
        if _budget_controller is not None:
            _budget_controller.reset_stats()
        _budget_controller = None


# ==================== Agent 使用判断 ====================

def should_use_agent(query: str, query_type: str = None,
                      classified_result=None) -> bool:
    """
    判断是否需要使用 Agent 流程

    规则：
    - META/SIMPLE/FILE_SPECIFIC: 不需要 Agent
    - COMPARISON/PROCESS: 需要 Agent
    - FACT: 根据复杂度判断

    Args:
        query: 用户查询
        query_type: 查询类型字符串
        classified_result: QueryClassifier.classify() 的返回结果

    Returns:
        是否需要 Agent 流程
    """
    # 如果有分类结果，使用它
    if classified_result is not None:
        # 检查是否跳过 LLM
        if hasattr(classified_result, 'skip_llm_decision') and classified_result.skip_llm_decision:
            return False

        # 获取查询类型
        qt = classified_result.query_type.value if hasattr(classified_result.query_type, 'value') \
            else str(classified_result.query_type)

        # 不需要 Agent 的类型
        if qt in ['META', 'SIMPLE', 'FILE_SPECIFIC', 'REALTIME']:
            return False

        # 需要 Agent 的类型
        if qt in ['COMPARISON', 'PROCESS']:
            return True

        # FACT 类型：根据复杂度判断
        if qt == 'FACT':
            # 查询长度
            if len(query) > 50:
                return True
            # 关键词数量
            if hasattr(classified_result, 'keywords') and len(classified_result.keywords) > 4:
                return True

        return False

    # 没有分类结果，使用简单规则
    if query_type:
        if query_type in ['META', 'SIMPLE', 'FILE_SPECIFIC']:
            return False
        if query_type in ['COMPARISON', 'PROCESS']:
            return True

    # 默认：简单查询（短查询）不走 Agent
    return len(query) > 30


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("LLM 预算控制器测试")
    print("=" * 60)

    controller = LLMBudgetController(BudgetConfig(max_calls_per_query=3))
    controller.start_query()

    # 模拟调用
    print("\n1. 检查调用限制")
    print(f"   can_call(REWRITE): {controller.can_call(CallType.REWRITE)}")
    print(f"   can_call(GENERATE): {controller.can_call(CallType.GENERATE)}")

    # 记录调用
    controller.record_call(CallType.REWRITE, tokens_used=500, description="查询重写")
    controller.record_call(CallType.GENERATE, tokens_used=1500, description="答案生成")

    print(f"\n2. 当前统计: {controller.get_current_stats()}")

    # 再次检查
    print(f"\n3. 再次检查（已调用2次）")
    print(f"   can_call(REWRITE): {controller.can_call(CallType.REWRITE)}")  # 应该 False（重写限制1次）
    print(f"   can_call(GENERATE): {controller.can_call(CallType.GENERATE)}")  # 应该 True

    # 第三次调用后检查
    controller.record_call(CallType.GENERATE, tokens_used=1000)
    print(f"\n4. 调用达到上限后: {controller.can_call(CallType.GENERATE)}")  # 应该 False

    # 结束查询
    stats = controller.end_query()
    print(f"\n5. 本次查询统计: {stats}")

    # Agent 判断测试
    print("\n" + "=" * 60)
    print("Agent 使用判断测试")
    print("=" * 60)

    test_cases = [
        ("什么是Python?", "SIMPLE"),
        ("比较 Python 和 Java 的区别", "COMPARISON"),
        ("请列出文档中的所有文件", "META"),
        ("如何部署这个服务？", "PROCESS"),
    ]

    for query, qtype in test_cases:
        result = should_use_agent(query, qtype)
        print(f"   '{query[:30]}...' [{qtype}] -> use_agent: {result}")
