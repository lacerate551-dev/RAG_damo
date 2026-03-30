"""
Graph RAG - 图谱增强检索模块

结合向量检索和图谱检索，提供更精准的知识问答

功能：
- 向量检索 + 图谱检索融合
- 多跳推理查询
- 实体感知检索
- 与现有 Agentic RAG 集成

使用方式：
    from graph_rag import GraphRAG

    rag = GraphRAG()
    result = rag.search("差旅管理办法由哪个部门负责？")
    print(result['answer'])
"""

import os
import sys
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# Windows 控制台编码处理
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 导入现有组件
from rag_demo import (
    search_knowledge,
    generate_answer,
    API_KEY,
    BASE_URL,
    MODEL
)

from graph_manager import GraphManager, Triple, get_graph_manager
from entity_extractor import EntityExtractor

# 尝试导入配置
try:
    from config import USE_GRAPH_RAG
except ImportError:
    USE_GRAPH_RAG = True

from openai import OpenAI


@dataclass
class GraphSearchResult:
    """图谱检索结果"""
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    context: str  # 图谱上下文文本


@dataclass
class MergedResult:
    """融合检索结果"""
    answer: str
    vector_contexts: List[Dict[str, Any]]
    graph_context: str
    entities: List[str]
    sources: List[Dict[str, Any]]


class GraphRAG:
    """
    图谱增强 RAG

    结合向量检索和知识图谱检索
    """

    def __init__(
        self,
        graph_manager: GraphManager = None,
        entity_extractor: EntityExtractor = None,
        enable_graph: bool = True
    ):
        """
        初始化 Graph RAG

        Args:
            graph_manager: 图谱管理器实例
            entity_extractor: 实体提取器实例
            enable_graph: 是否启用图谱检索
        """
        self.enable_graph = enable_graph and USE_GRAPH_RAG

        # 初始化图谱管理器
        if graph_manager:
            self.graph_manager = graph_manager
        elif self.enable_graph:
            self.graph_manager = get_graph_manager()
        else:
            self.graph_manager = None

        # 初始化实体提取器
        if entity_extractor:
            self.entity_extractor = entity_extractor
        else:
            self.entity_extractor = EntityExtractor() if self.enable_graph else None

        # LLM 客户端
        self.llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    def search(
        self,
        query: str,
        top_k: int = 5,
        graph_depth: int = 2,
        verbose: bool = False
    ) -> MergedResult:
        """
        主检索接口：向量检索 + 图谱检索融合

        Args:
            query: 用户查询
            top_k: 向量检索返回数量
            graph_depth: 图谱搜索深度
            verbose: 是否打印详细过程

        Returns:
            MergedResult 包含答案和上下文
        """
        if verbose:
            print(f"\n[Graph RAG] 处理查询: {query}")

        # 1. 向量检索
        if verbose:
            print("[1] 执行向量检索...")
        vector_results = search_knowledge(query, top_k=top_k)
        vector_contexts = self._format_vector_results(vector_results)

        # 2. 图谱检索（如果启用）
        graph_context = ""
        entities = []

        if self.enable_graph and self.graph_manager and self.graph_manager.connected:
            if verbose:
                print("[2] 执行图谱检索...")

            # 从查询中提取实体
            entities = self._extract_query_entities(query, verbose)

            if entities:
                # 图谱检索
                graph_result = self._retrieve_from_graph(entities, graph_depth)
                graph_context = graph_result.context

                if verbose:
                    print(f"    提取到 {len(entities)} 个实体")
                    print(f"    图谱找到 {len(graph_result.nodes)} 个节点, {len(graph_result.edges)} 条边")
        else:
            if verbose:
                print("[2] 图谱检索未启用，跳过")

        # 3. 融合上下文生成答案
        if verbose:
            print("[3] 生成答案...")

        merged_context = self._merge_contexts(vector_contexts, graph_context)
        answer = self._generate_answer(query, merged_context, entities)

        # 4. 提取来源
        sources = self._extract_sources(vector_contexts)

        return MergedResult(
            answer=answer,
            vector_contexts=vector_contexts,
            graph_context=graph_context,
            entities=entities,
            sources=sources
        )

    def _extract_query_entities(
        self,
        query: str,
        verbose: bool = False
    ) -> List[str]:
        """
        从查询中提取实体

        Args:
            query: 用户查询
            verbose: 是否打印详细过程

        Returns:
            实体名称列表
        """
        # 使用 LLM 快速提取查询中的实体
        prompt = f"""从以下问题中提取关键实体（如制度名称、部门名称、人员角色等）。
只返回实体名称，每行一个，不要输出其他内容。

问题：{query}

实体："""

        try:
            response = self.llm_client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=100
            )

            content = response.choices[0].message.content.strip()
            entities = [line.strip() for line in content.split('\n') if line.strip()]
            return entities[:5]  # 最多返回5个实体

        except Exception as e:
            if verbose:
                print(f"    实体提取失败: {e}")
            return []

    def _retrieve_from_graph(
        self,
        entities: List[str],
        depth: int = 2
    ) -> GraphSearchResult:
        """
        从图谱中检索相关子图

        Args:
            entities: 实体名称列表
            depth: 搜索深度

        Returns:
            GraphSearchResult 包含节点、边和上下文
        """
        if not self.graph_manager or not self.graph_manager.connected:
            return GraphSearchResult(nodes=[], edges=[], context="")

        # 搜索子图
        subgraph = self.graph_manager.search_subgraph(entities, depth)

        # 构建上下文文本
        context = self._build_graph_context(subgraph)

        return GraphSearchResult(
            nodes=subgraph['nodes'],
            edges=subgraph['edges'],
            context=context
        )

    def _build_graph_context(self, subgraph: Dict) -> str:
        """
        将子图转换为自然语言上下文

        Args:
            subgraph: 子图数据

        Returns:
            上下文文本
        """
        if not subgraph['nodes'] and not subgraph['edges']:
            return ""

        lines = ["【知识图谱信息】"]

        # 转换关系类型回中文
        relation_map = {
            "RESPONSIBLE_FOR": "负责",
            "APPLIES_TO": "适用",
            "CONTAINS": "包含",
            "APPROVES": "审批",
            "HAS_LIMIT": "限额",
            "HAS_DEADLINE": "时效",
            "HAS_CONDITION": "条件",
            "RELATED_TO": "相关",
            "BELONGS_TO": "属于",
            "MANAGES": "管理",
        }

        # 构建关系描述
        if subgraph['edges']:
            lines.append("实体关系：")
            for edge in subgraph['edges'][:20]:  # 限制数量
                relation = edge.get('type', '相关')
                relation_cn = relation_map.get(relation, relation)
                lines.append(f"  - {edge['from']} {relation_cn} {edge['to']}")

        return '\n'.join(lines)

    def _format_vector_results(self, results: Dict) -> List[Dict]:
        """格式化向量检索结果"""
        contexts = []
        docs = results.get('documents', [[]])[0]
        metas = results.get('metadatas', [[]])[0]

        for doc, meta in zip(docs, metas):
            contexts.append({
                'content': doc,
                'metadata': meta,
                'source_type': '知识库'
            })

        return contexts

    def _merge_contexts(
        self,
        vector_contexts: List[Dict],
        graph_context: str
    ) -> str:
        """
        融合向量检索和图谱检索的上下文

        Args:
            vector_contexts: 向量检索结果
            graph_context: 图谱上下文

        Returns:
            融合后的上下文文本
        """
        parts = []

        # 添加图谱上下文
        if graph_context:
            parts.append(graph_context)
            parts.append("")

        # 添加向量检索上下文
        if vector_contexts:
            parts.append("【知识库文档】")
            for i, ctx in enumerate(vector_contexts, 1):
                source = ctx['metadata'].get('source', '未知来源')
                parts.append(f"\n[文档 {i}] 来源: {source}")
                parts.append(ctx['content'])

        return '\n'.join(parts)

    def _generate_answer(
        self,
        query: str,
        context: str,
        entities: List[str]
    ) -> str:
        """
        基于融合上下文生成答案

        Args:
            query: 用户查询
            context: 融合上下文
            entities: 提取的实体

        Returns:
            生成的答案
        """
        # 如果有图谱信息，强调实体关系
        entity_hint = ""
        if entities:
            entity_hint = f"\n注意：问题涉及以下实体：{', '.join(entities)}"

        prompt = f"""基于以下知识库文档和知识图谱信息回答问题。

{context}
{entity_hint}

请根据上述信息回答问题，要求：
1. 优先使用知识图谱中的实体关系信息
2. 结合知识库文档提供详细说明
3. 如果信息不足，请诚实说明
4. 回答要简洁准确

问题：{query}

回答："""

        # 直接调用 LLM 生成答案，不使用 rag_demo 的 generate_answer
        try:
            response = self.llm_client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"生成答案失败: {str(e)}"

    def _extract_sources(self, contexts: List[Dict]) -> List[Dict]:
        """提取来源信息"""
        sources = []
        for ctx in contexts:
            meta = ctx.get('metadata', {})
            sources.append({
                'source': meta.get('source', '未知'),
                'page': meta.get('page', ''),
                'type': ctx.get('source_type', '知识库')
            })
        return sources

    # ==================== 高级检索方法 ====================

    def multi_hop_query(
        self,
        query: str,
        hops: int = 2,
        verbose: bool = False
    ) -> MergedResult:
        """
        多跳查询：通过图谱关系链进行推理

        例如："出差补助的审批流程是什么？"
        -> 出差补助 (制度) --适用--> 员工
        -> 出差补助 (制度) --包含--> 审批流程
        -> 审批流程 (流程) --审批--> 部门负责人

        Args:
            query: 用户查询
            hops: 最大跳数
            verbose: 是否打印详细过程

        Returns:
            MergedResult
        """
        if verbose:
            print(f"\n[多跳查询] {query}")

        # 先进行常规检索获取初始实体
        initial_result = self.search(query, top_k=3, graph_depth=hops, verbose=verbose)

        # 如果图谱信息充足，直接返回
        if initial_result.graph_context:
            return initial_result

        # 否则扩展搜索
        if verbose:
            print("[扩展搜索] 尝试从知识库文档中提取更多实体...")

        # 从向量检索结果中提取实体
        all_entities = list(initial_result.entities)
        for ctx in initial_result.vector_contexts[:3]:
            if self.entity_extractor:
                extraction = self.entity_extractor.extract(ctx['content'][:1000])
                for triple in extraction.triples[:5]:
                    all_entities.append(triple.head.name)
                    all_entities.append(triple.tail.name)

        # 去重
        unique_entities = list(set(all_entities))[:10]

        if unique_entities:
            # 用扩展后的实体重新检索
            graph_result = self._retrieve_from_graph(unique_entities, hops)
            if graph_result.context:
                initial_result.graph_context = graph_result.context
                initial_result.entities = unique_entities

                # 重新生成答案
                merged = self._merge_contexts(
                    initial_result.vector_contexts,
                    graph_result.context
                )
                initial_result.answer = self._generate_answer(
                    query, merged, unique_entities
                )

        return initial_result

    def relation_aware_search(
        self,
        query: str,
        relation_type: str = None,
        verbose: bool = False
    ) -> MergedResult:
        """
        关系感知检索：根据特定关系类型检索

        Args:
            query: 用户查询
            relation_type: 关系类型（如：负责、适用、包含等）
            verbose: 是否打印详细过程

        Returns:
            MergedResult
        """
        if verbose:
            print(f"\n[关系感知检索] 关系类型: {relation_type}")

        # 先进行常规检索
        result = self.search(query, verbose=verbose)

        # 如果指定了关系类型，从图谱中获取相关三元组
        if relation_type and self.graph_manager and self.graph_manager.connected:
            triples = self.graph_manager.search_by_relation(relation_type)

            if triples and verbose:
                print(f"  找到 {len(triples)} 个 '{relation_type}' 关系")
                for t in triples[:5]:
                    print(f"    {t['head']} -> {t['relation']} -> {t['tail']}")

            # 添加到上下文
            if triples:
                relation_context = "\n【关系检索结果】\n"
                for t in triples[:10]:
                    relation_context += f"  - {t['head']} {t['relation']} {t['tail']}\n"

                result.graph_context = relation_context + result.graph_context

                # 重新生成答案
                merged = self._merge_contexts(
                    result.vector_contexts,
                    result.graph_context
                )
                result.answer = self._generate_answer(query, merged, result.entities)

        return result


# ==================== 便捷函数 ====================

def graph_rag_query(
    query: str,
    enable_graph: bool = True,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    便捷函数：执行 Graph RAG 查询

    Args:
        query: 用户查询
        enable_graph: 是否启用图谱检索
        verbose: 是否打印详细过程

    Returns:
        包含答案和元信息的字典
    """
    rag = GraphRAG(enable_graph=enable_graph)
    result = rag.search(query, verbose=verbose)

    return {
        'answer': result.answer,
        'entities': result.entities,
        'sources': result.sources,
        'has_graph_context': bool(result.graph_context)
    }


# ==================== 与 Agentic RAG 集成 ====================

def should_use_graph(query: str) -> bool:
    """
    判断查询是否适合使用图谱检索

    Args:
        query: 用户查询

    Returns:
        是否应该使用图谱检索
    """
    # 图谱检索适合的场景关键词
    graph_keywords = [
        "负责", "管理", "属于", "包含", "相关",
        "哪个部门", "谁负责", "什么流程", "什么条件",
        "审批", "适用", "限额", "标准", "规定",
        "关系", "关联", "是否", "有没有"
    ]

    query_lower = query.lower()
    return any(kw in query_lower for kw in graph_keywords)


# ==================== 测试代码 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Graph RAG 测试")
    print("=" * 60)

    # 检查图谱连接
    rag = GraphRAG()

    if rag.graph_manager and rag.graph_manager.connected:
        print("✓ Neo4j 已连接")
    else:
        print("✗ Neo4j 未连接，将仅使用向量检索")

    # 测试查询
    test_queries = [
        "差旅管理办法由哪个部门负责？",
        "出差补助标准是多少？",
        "员工报销流程是什么？",
    ]

    for query in test_queries:
        print(f"\n{'=' * 60}")
        print(f"查询: {query}")
        print("=" * 60)

        result = rag.search(query, verbose=True)

        print(f"\n[答案]\n{result.answer}")
        print(f"\n[实体] {result.entities}")
        print(f"[图谱上下文] {'有' if result.graph_context else '无'}")
