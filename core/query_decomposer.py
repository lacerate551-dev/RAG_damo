"""
Query 拆分器 - 复杂查询分解

核心功能：
1. 识别需要拆分的复杂查询
2. 将对比类、推理类问题拆分为子查询
3. 支持并行检索和结果合并

使用方式：
    from core.query_decomposer import QueryDecomposer

    decomposer = QueryDecomposer()
    result = decomposer.decompose("Transformer 和 CNN 的区别是什么？")
    print(result.sub_queries)  # ["Transformer的核心原理", "CNN的核心原理", "两者的主要区别"]
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import re


@dataclass
class DecomposedQuery:
    """拆分后的查询结果"""
    original_query: str              # 原始查询
    sub_queries: List[str]           # 子查询列表
    query_type: str                  # 拆分类型 (comparison, multi_concept, reasoning)
    entities: List[str]              # 识别的实体
    needs_merge: bool                # 是否需要合并答案
    merge_strategy: str              # 合并策略 (compare, summarize, synthesize)

    def to_dict(self) -> dict:
        return {
            "original_query": self.original_query,
            "sub_queries": self.sub_queries,
            "query_type": self.query_type,
            "entities": self.entities,
            "needs_merge": self.needs_merge,
            "merge_strategy": self.merge_strategy
        }


class QueryDecomposer:
    """
    查询拆分器

    拆分策略：
    1. 对比类查询：拆分为各实体的独立查询 + 对比查询
    2. 多概念查询：拆分为各概念的独立查询
    3. 推理类查询：拆分为前提验证 + 推理步骤

    触发条件：
    - 包含"区别"、"对比"、"比较"等关键词
    - 包含多个实体
    - 复杂推理问题
    """

    # 对比类关键词
    COMPARISON_KEYWORDS = [
        "区别", "对比", "比较", "差异", "不同", "差别",
        "哪个更好", "哪个更", "vs", "VS", "还是",
        "一样吗", "有什么不同", "有什么区别",
        "优缺点", "利弊", "优劣", "相比"
    ]

    # 多实体连接词
    ENTITY_CONNECTORS = ["和", "与", "跟", "及", "以及", "和", "同"]

    # 推理类关键词
    REASONING_KEYWORDS = [
        "为什么", "原因", "怎么导致", "如何影响",
        "怎么会", "为何", "是什么导致"
    ]

    # 列举类关键词
    LIST_KEYWORDS = [
        "有哪些", "有什么", "列举", "分别",
        "都有哪些", "各有什么"
    ]

    def __init__(self, llm_client=None, llm_model: str = None):
        """
        初始化拆分器

        Args:
            llm_client: LLM客户端（可选，用于复杂拆分）
            llm_model: 模型名称
        """
        self.llm_client = llm_client
        self.llm_model = llm_model

    def should_decompose(self, query: str) -> Tuple[bool, str]:
        """
        判断是否需要拆分

        Args:
            query: 用户查询

        Returns:
            (needs_decompose, decompose_type)
        """
        # 对比类查询
        if any(kw in query for kw in self.COMPARISON_KEYWORDS):
            # 检查是否有多个实体
            entities = self._extract_entities_for_comparison(query)
            if len(entities) >= 2:
                return True, "comparison"

        # 推理类查询（复杂）
        if any(kw in query for kw in self.REASONING_KEYWORDS):
            # 简单推理不拆分
            if len(query) > 30:  # 长推理问题
                return True, "reasoning"

        return False, ""

    def decompose(self, query: str) -> DecomposedQuery:
        """
        拆分查询

        Args:
            query: 用户查询

        Returns:
            DecomposedQuery: 拆分结果
        """
        needs_decompose, decompose_type = self.should_decompose(query)

        if not needs_decompose:
            return DecomposedQuery(
                original_query=query,
                sub_queries=[query],
                query_type="simple",
                entities=[],
                needs_merge=False,
                merge_strategy="none"
            )

        if decompose_type == "comparison":
            return self._decompose_comparison(query)
        elif decompose_type == "reasoning":
            return self._decompose_reasoning(query)

        return DecomposedQuery(
            original_query=query,
            sub_queries=[query],
            query_type="unknown",
            entities=[],
            needs_merge=False,
            merge_strategy="none"
        )

    def _decompose_comparison(self, query: str) -> DecomposedQuery:
        """
        拆分对比类查询

        示例：
            "A和B的区别是什么？" → ["A的核心原理是什么？", "B的核心原理是什么？", "A和B的主要区别有哪些？"]
        """
        entities = self._extract_entities_for_comparison(query)
        entities = [e for e in entities if len(e) >= 2]  # 过滤短实体

        if len(entities) < 2:
            # 无法识别实体，返回原查询
            return DecomposedQuery(
                original_query=query,
                sub_queries=[query],
                query_type="comparison_fallback",
                entities=[],
                needs_merge=False,
                merge_strategy="none"
            )

        sub_queries = []

        # 为每个实体创建独立查询
        for entity in entities:
            sub_queries.append(f"{entity}是什么？")
            sub_queries.append(f"{entity}的主要特点有哪些？")

        # 添加对比查询
        entity_str = "和".join(entities[:2])  # 最多两个实体
        sub_queries.append(f"{entity_str}的主要区别有哪些？")

        # 去重
        sub_queries = list(dict.fromkeys(sub_queries))

        return DecomposedQuery(
            original_query=query,
            sub_queries=sub_queries,
            query_type="comparison",
            entities=entities,
            needs_merge=True,
            merge_strategy="compare"
        )

    def _decompose_reasoning(self, query: str) -> DecomposedQuery:
        """
        拆分推理类查询

        示例：
            "为什么A会导致B？" → ["A是什么？", "B是什么？", "A和B的关系是什么？", "A导致B的原因是什么？"]
        """
        # 简单实现：提取关键概念
        # 尝试使用LLM进行更精确的拆分
        if self.llm_client:
            return self._llm_decompose(query, "reasoning")

        # 降级：返回原查询 + 相关概念查询
        return DecomposedQuery(
            original_query=query,
            sub_queries=[query, f"{query[:10]}...的相关背景"],
            query_type="reasoning",
            entities=[],
            needs_merge=True,
            merge_strategy="synthesize"
        )

    def _llm_decompose(self, query: str, query_type: str) -> DecomposedQuery:
        """
        使用LLM进行查询拆分

        Args:
            query: 原始查询
            query_type: 查询类型

        Returns:
            DecomposedQuery
        """
        if not self.llm_client:
            return DecomposedQuery(
                original_query=query,
                sub_queries=[query],
                query_type=query_type,
                entities=[],
                needs_merge=False,
                merge_strategy="none"
            )

        prompt = f"""请将以下复杂查询拆分为多个简单的子查询，便于分别检索。

原始查询：{query}

要求：
1. 每个子查询应该简单明确，便于检索
2. 子查询应该覆盖原查询的关键信息需求
3. 返回JSON格式：{{"sub_queries": ["子查询1", "子查询2", ...], "entities": ["实体1", "实体2"], "merge_strategy": "compare/summarize/synthesize"}}

只返回JSON，不要其他内容。"""

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300
            )

            import json
            result_text = response.choices[0].message.content.strip()

            # 解析JSON
            json_match = re.search(r'\{[^}]+\}', result_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                sub_queries = data.get('sub_queries', [query])
                entities = data.get('entities', [])
                merge_strategy = data.get('merge_strategy', 'synthesize')

                return DecomposedQuery(
                    original_query=query,
                    sub_queries=sub_queries if sub_queries else [query],
                    query_type=query_type,
                    entities=entities,
                    needs_merge=True,
                    merge_strategy=merge_strategy
                )
        except Exception as e:
            # LLM拆分失败，返回原查询
            pass

        return DecomposedQuery(
            original_query=query,
            sub_queries=[query],
            query_type=query_type,
            entities=[],
            needs_merge=False,
            merge_strategy="none"
        )

    def _extract_entities_for_comparison(self, query: str) -> List[str]:
        """
        从对比类查询中提取实体

        示例：
            "A和B的区别" → ["A", "B"]
            "年假和病假有什么不同" → ["年假", "病假"]
        """
        entities = []

        # 预处理：移除常见的疑问后缀
        query_clean = query
        suffixes = ["有什么区别", "的区别是什么", "有什么不同", "的不同是什么",
                   "的区别", "的不同", "对比", "比较", "哪个更好", "哪个更"]
        for suffix in suffixes:
            if query_clean.endswith(suffix):
                query_clean = query_clean[:-len(suffix)]
                break

        # 方法1：使用连接词分割
        for connector in self.ENTITY_CONNECTORS:
            if connector in query_clean:
                parts = query_clean.split(connector)
                if len(parts) >= 2:
                    # 提取第一个部分的主语
                    first = self._clean_entity(parts[0])
                    # 提取第二个部分的主语
                    second = self._clean_entity(parts[1])

                    if first and 2 <= len(first) <= 10:
                        entities.append(first)
                    if second and 2 <= len(second) <= 10:
                        entities.append(second)
                break

        # 方法2：使用正则匹配常见模式
        if not entities:
            # 模式：实体1和实体2
            match = re.search(r'([^\s，。？!！?？和与跟及]+)[和与跟及]([^\s，。？!！?？的]+)', query)
            if match:
                e1 = match.group(1).strip()
                e2 = match.group(2).strip()
                if len(e1) >= 2 and len(e1) <= 10:
                    entities.append(e1)
                if len(e2) >= 2 and len(e2) <= 10:
                    entities.append(e2)

        # 去重
        entities = list(dict.fromkeys(entities))

        return entities[:3]  # 最多3个实体

    def _clean_entity(self, text: str) -> str:
        """
        清理实体文本

        移除常见的修饰词和标点
        """
        text = text.strip()

        # 移除开头的修饰词
        prefixes = ["请问", "我想知道", "帮我查", "查一下"]
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):]

        # 移除结尾的标点和疑问词
        text = re.sub(r'[？?！!。，,、]+$', '', text)
        text = re.sub(r'(是什么|有什么|有哪些|怎么样|如何|有什么区别|有什么不同)$', '', text)

        # 移除结尾的"区别"、"不同"等
        text = re.sub(r'(的区别|的不同|区别|不同)$', '', text)

        return text.strip()

    # ==================== 扩展接口 ====================

    def decompose_with_context(
        self,
        query: str,
        history: List[dict] = None,
        context: str = None
    ) -> DecomposedQuery:
        """
        带上下文的查询拆分

        Args:
            query: 用户查询
            history: 对话历史
            context: 额外上下文

        Returns:
            DecomposedQuery
        """
        # 当前实现不需要上下文，预留接口
        return self.decompose(query)


# ==================== 便捷函数 ====================

def decompose_query(query: str, llm_client=None, llm_model: str = None) -> DecomposedQuery:
    """
    便捷函数：拆分查询

    Args:
        query: 用户查询
        llm_client: LLM客户端（可选）
        llm_model: 模型名称

    Returns:
        DecomposedQuery: 拆分结果
    """
    decomposer = QueryDecomposer(llm_client=llm_client, llm_model=llm_model)
    return decomposer.decompose(query)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    # 测试用例
    test_queries = [
        # 对比类
        "年假和病假有什么区别？",
        "Transformer和CNN的对比",
        "A和B哪个更好？",
        "主导品规和护卫品规有什么区别？",

        # 推理类
        "为什么2022年三峡电站发电量较低？",

        # 简单查询（不需要拆分）
        "货源投放的总体要求是什么？",
        "报销标准",
    ]

    decomposer = QueryDecomposer()

    print("=" * 60)
    print("查询拆分器测试")
    print("=" * 60)

    for query in test_queries:
        result = decomposer.decompose(query)
        print(f"\n原始查询: {query}")
        print(f"拆分类型: {result.query_type}")
        print(f"实体: {result.entities}")
        print(f"子查询: {result.sub_queries}")
        print(f"需要合并: {result.needs_merge} ({result.merge_strategy})")
