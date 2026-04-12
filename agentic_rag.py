"""
Agentic RAG - 知识库智能问答系统

核心能力：
1. 知识库检索 - 向量检索 + BM25 + Rerank
2. 网络搜索 - 当知识库不足时自动搜索（需配置SERPER_API_KEY）
3. 图谱检索 - 实体关系推理（需配置Neo4j）
4. 多源融合 - 智能处理知识库和网络内容
5. Agent决策 - 动态决定检索、改写、分解等操作

使用方式：
    from agentic_rag import AgenticRAG

    rag = AgenticRAG()
    result = rag.process("你的问题")
    print(result["answer"])

配置（可选）：
- 在config.py中添加 SERPER_API_KEY 启用网络搜索
- 在config.py中配置 Neo4j 启用图谱检索
"""

import json
import sys
import requests
from openai import OpenAI

# 导入现有RAG组件
from rag_demo import (
    search_knowledge,
    generate_answer,
    collection,
    API_KEY,
    BASE_URL,
    MODEL,
    check_restricted_documents
)

# 尝试导入搜索API配置
try:
    from config import SERPER_API_KEY
    HAS_SERPER = True
except ImportError:
    HAS_SERPER = False
    SERPER_API_KEY = None

# 尝试导入 Graph RAG 组件
try:
    from config import USE_GRAPH_RAG
except ImportError:
    USE_GRAPH_RAG = False

try:
    from graph import GraphRAG, should_use_graph
    HAS_GRAPH_RAG = True
except ImportError:
    HAS_GRAPH_RAG = False


class AgenticRAG:
    """
    Agentic RAG - 知识库智能问答

    支持能力：
    - 知识库检索：向量检索 + BM25 + Rerank
    - 网络搜索：知识库不足时自动搜索
    - 图谱检索：实体关系推理
    - 多源融合：智能处理知识库和网络内容
    - Agent决策：动态决定检索、改写、分解等操作
    """

    def __init__(
        self,
        max_iterations: int = 3,
        enable_web_search: bool = True,
        enable_graph: bool = True
    ):
        """
        初始化

        Args:
            max_iterations: 最大迭代次数
            enable_web_search: 是否启用网络搜索
            enable_graph: 是否启用图谱检索
        """
        self.max_iterations = max_iterations
        self.enable_web_search = enable_web_search and HAS_SERPER
        self.enable_graph = enable_graph and HAS_GRAPH_RAG and USE_GRAPH_RAG
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

        # 初始化图谱检索
        self.graph_rag = None
        if self.enable_graph:
            try:
                self.graph_rag = GraphRAG()
                if self.graph_rag.graph_manager and self.graph_rag.graph_manager.connected:
                    print("✓ Graph RAG 已启用")
                else:
                    self.graph_rag = None
                    self.enable_graph = False
            except Exception as e:
                print(f"✗ Graph RAG 初始化失败: {e}")
                self.graph_rag = None
                self.enable_graph = False

        # 信息来源标记
        self.SOURCE_KB = "知识库"
        self.SOURCE_WEB = "网络搜索"
        self.SOURCE_GRAPH = "知识图谱"

    def process(self, query: str, verbose: bool = True, history: list = None,
                log_callback=None, allowed_levels: list = None,
                role: str = None, department: str = None,
                collections: list = None) -> dict:
        """
        主处理流程

        Args:
            query: 用户问题
            verbose: 是否打印详细过程
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]
            log_callback: 日志回调函数，用于实时推送思考过程
            allowed_levels: 允许访问的安全级别列表，如 ["public", "internal"]
            role: 用户角色（多向量库模式），如 "admin", "manager", "user"
            department: 用户部门（多向量库模式），如 "tech", "finance"
            collections: 指定查询的向量库列表（可选，不传则自动路由）

        Returns:
            {
                "answer": 回答内容,
                "iterations": 迭代次数,
                "reasoning": 推理过程,
                "contexts": 检索到的上下文,
                "sources": 来源列表,
                "log_trace": 完整日志记录
            }
        """
        import time
        start_time = time.time()
        log_trace = []  # 完整日志记录

        def emit_log(event_type, data):
            """发送日志事件"""
            log_entry = {
                "type": event_type,
                "timestamp": time.time() - start_time,
                **data
            }
            log_trace.append(log_entry)
            if log_callback:
                log_callback(log_entry)

        emit_log("start", {"query": query})

        if verbose:
            print("\n" + "=" * 60)
            print(f"[用户] {query}")
            print("=" * 60)

        # 检查是否为元问题（关于知识库本身的问题）
        if self._is_meta_question(query):
            if verbose:
                print("\n[元问题] 检测到关于知识库本身的问题")
            emit_log("decision", {"action": "meta_query", "reason": "检测到元问题，直接回答"})

            answer = self._answer_meta_question(query, allowed_levels, role=role, department=department)
            emit_log("answer", {"reason": "元问题直接回答"})

            return {
                "answer": answer,
                "iterations": 0,
                "reasoning": [{"type": "meta_question", "query": query}],
                "contexts": [],
                "sources": [],
                "log_trace": log_trace
            }

        # 知识问答流程
        all_contexts = []
        reasoning_trace = []
        current_query = query
        iteration = 0

        if verbose:
            print("\n[开始检索...]")

        while iteration < self.max_iterations:
            iteration += 1
            iter_start = time.time()

            if verbose:
                print(f"\n--- 第 {iteration} 轮迭代 ---")

            # Agent决策
            think_start = time.time()
            decision = self._think(query, current_query, all_contexts, reasoning_trace)
            think_duration = (time.time() - think_start) * 1000

            emit_log("decision", {
                "iteration": iteration,
                "action": decision['action'],
                "reason": decision.get('reason', ''),
                "duration_ms": round(think_duration, 0)
            })

            reasoning_trace.append({
                "iteration": iteration,
                "query": current_query,
                "decision": decision
            })

            if verbose:
                print(f"[决策] {decision['action']}")
                if decision.get('reason'):
                    print(f"   理由: {decision['reason']}")

            # 执行决策
            if decision["action"] == "answer":
                # 生成答案
                answer_start = time.time()
                answer = self._generate_fused_answer(query, all_contexts, allowed_levels)
                answer_duration = (time.time() - answer_start) * 1000

                emit_log("answer", {
                    "duration_ms": round(answer_duration, 0),
                    "total_duration_ms": round((time.time() - start_time) * 1000, 0)
                })

                sources = self._extract_sources(all_contexts)
                return {
                    "answer": answer,
                    "iterations": iteration,
                    "reasoning": reasoning_trace,
                    "contexts": all_contexts,
                    "sources": sources,
                    "log_trace": log_trace
                }

            elif decision["action"] == "kb_search":
                # 知识库检索
                search_start = time.time()
                if verbose:
                    print(f"[知识库检索] {current_query}")

                results = search_knowledge(current_query, top_k=5, allowed_levels=allowed_levels,
                                           role=role, department=department, collections=collections)
                docs = results.get('documents', [[]])[0]
                metas = results.get('metadatas', [[]])[0]

                for doc, meta in zip(docs, metas):
                    all_contexts.append({
                        'doc': doc,
                        'meta': meta,
                        'source_type': self.SOURCE_KB,
                        'query': current_query
                    })

                search_duration = (time.time() - search_start) * 1000
                emit_log("retrieve", {
                    "source": "知识库",
                    "query": current_query,
                    "count": len(docs),
                    "duration_ms": round(search_duration, 0),
                    "snippets": [
                        {"source": m.get('source', '未知'), "page": m.get('page'), "text": d[:100] + "..."}
                        for d, m in zip(docs[:3], metas[:3])
                    ]
                })

                if verbose:
                    print(f"   找到 {len(docs)} 个片段")

                # 评估知识库检索结果是否足够
                if docs and self._is_kb_result_sufficient(current_query, docs):
                    if verbose:
                        print("   [评估] 知识库结果足够，跳过网络搜索")
                    # 标记跳过网络搜索
                    reasoning_trace[-1]["skip_web_search"] = True

            elif decision["action"] == "web_search":
                # 网络搜索
                if not self.enable_web_search:
                    if verbose:
                        print("[警告] 网络搜索未配置，跳过")
                    emit_log("warning", {"message": "网络搜索未配置"})
                    continue

                # 检查是否已经跳过网络搜索（知识库结果足够）
                if reasoning_trace and reasoning_trace[-1].get("skip_web_search"):
                    if verbose:
                        print("[跳过] 知识库结果已足够，无需网络搜索")
                    emit_log("skip", {"reason": "知识库结果足够，跳过网络搜索"})
                    continue

                # 检查知识库是否有足够结果
                if kb_count > 0:
                    # 获取知识库文档内容
                    kb_docs = [c['doc'] for c in all_contexts if c.get('source_type') == self.SOURCE_KB]
                    if self._is_kb_result_sufficient(current_query, kb_docs):
                        if verbose:
                            print("[跳过] 知识库结果已足够，无需网络搜索")
                        emit_log("skip", {"reason": "知识库结果足够，跳过网络搜索"})
                        continue

                search_query = decision.get('search_query', current_query)
                search_start = time.time()
                if verbose:
                    print(f"[网络搜索] {search_query}")

                web_results = self._web_search(search_query)
                for result in web_results:
                    all_contexts.append({
                        'doc': result['snippet'],
                        'meta': {
                            'source': result['link'],
                            'title': result['title'],
                            'date': result.get('date', '')
                        },
                        'source_type': self.SOURCE_WEB,
                        'query': search_query
                    })

                search_duration = (time.time() - search_start) * 1000
                emit_log("retrieve", {
                    "source": "网络搜索",
                    "query": search_query,
                    "count": len(web_results),
                    "duration_ms": round(search_duration, 0),
                    "snippets": [
                        {"title": r.get('title', ''), "source": r.get('link', ''), "text": r.get('snippet', '')[:100] + "..."}
                        for r in web_results[:3]
                    ]
                })

                if verbose:
                    print(f"   找到 {len(web_results)} 条结果")

            elif decision["action"] == "graph_search":
                # 图谱检索
                if not self.enable_graph:
                    if verbose:
                        print("[提示] 图谱检索未启用，使用知识库检索")
                    emit_log("warning", {"message": "图谱检索未启用"})
                    decision["action"] = "kb_search"
                    continue

                if verbose:
                    print(f"[图谱检索] {current_query}")

                search_start = time.time()
                graph_results = self._graph_search(current_query, verbose, allowed_levels=allowed_levels)
                for result in graph_results:
                    all_contexts.append(result)

                search_duration = (time.time() - search_start) * 1000
                emit_log("retrieve", {
                    "source": "知识图谱",
                    "query": current_query,
                    "count": len(graph_results),
                    "duration_ms": round(search_duration, 0),
                    "snippets": [
                        {"text": r.get('doc', '')[:100] + "..."}
                        for r in graph_results[:3]
                    ]
                })

                if verbose and graph_results:
                    print(f"   找到 {len(graph_results)} 条结果")

            elif decision["action"] == "rewrite":
                old_query = current_query
                current_query = decision.get("new_query", current_query)
                emit_log("rewrite", {"old_query": old_query, "new_query": current_query})
                if verbose:
                    print(f"[改写查询] {current_query}")

            elif decision["action"] == "decompose":
                sub_queries = decision.get("sub_queries", [])
                emit_log("decompose", {"sub_queries": sub_queries})
                if verbose:
                    print(f"[分解问题] {len(sub_queries)} 个子问题")

                for sub_q in sub_queries:
                    results = search_knowledge(sub_q, top_k=3, allowed_levels=allowed_levels,
                                                role=role, department=department, collections=collections)
                    docs = results.get('documents', [[]])[0]
                    metas = results.get('metadatas', [[]])[0]
                    for doc, meta in zip(docs, metas):
                        all_contexts.append({
                            'doc': doc,
                            'meta': meta,
                            'source_type': self.SOURCE_KB,
                            'query': sub_q
                        })

        # 达到迭代上限
        emit_log("max_iterations", {"iterations": iteration})
        answer = self._generate_fused_answer(query, all_contexts, allowed_levels)
        sources = self._extract_sources(all_contexts)

        emit_log("complete", {
            "total_duration_ms": round((time.time() - start_time) * 1000, 0)
        })

        return {
            "answer": answer,
            "iterations": iteration,
            "reasoning": reasoning_trace,
            "contexts": all_contexts,
            "sources": sources,
            "log_trace": log_trace
        }

    def _extract_sources(self, contexts: list) -> list:
        """提取来源列表，合并同一来源"""
        # 按来源分组
        source_map = {}  # {source_key: {"source": str, "type": str, "count": int, "pages": list}}

        for c in contexts:
            meta = c.get('meta', {})
            source_type = c.get('source_type', '未知')

            if source_type == self.SOURCE_KB:
                source_key = meta.get('source', '未知')
                page = meta.get('page')
            elif source_type == self.SOURCE_GRAPH:
                entities = c.get('entities', [])
                source_key = "知识图谱"
                if entities:
                    source_key += f" ({', '.join(entities[:3])})"
                page = None
            else:
                source_key = meta.get('title', meta.get('source', '未知'))
                page = None

            # 合并同一来源
            if source_key not in source_map:
                source_map[source_key] = {
                    "source": source_key,
                    "type": source_type,
                    "count": 0,
                    "pages": []
                }

            source_map[source_key]["count"] += 1
            if page:
                if page not in source_map[source_key]["pages"]:
                    source_map[source_key]["pages"].append(page)

        # 构建结果列表
        sources = []
        for key, info in source_map.items():
            source_str = info["source"]
            # 如果有页码信息，添加到来源名称
            if info["pages"]:
                pages_str = ", ".join(f"第{p}页" for p in sorted(info["pages"]))
                source_str = f"{source_str} ({pages_str})"

            sources.append({
                "source": source_str,
                "type": info["type"],
                "count": info["count"]  # 添加引用次数
            })

        return sources

    def _think(self, original_query: str, current_query: str,
               contexts: list, history: list) -> dict:
        """
        Agent决策

        决策类型：
        - kb_search: 检索知识库
        - web_search: 网络搜索
        - graph_search: 图谱检索（实体关系推理）
        - answer: 生成答案
        - rewrite: 改写查询
        - decompose: 分解问题
        - meta_answer: 元问题直接回答（关于系统/权限/目录的问题）
        """
        # 分析现有信息
        kb_count = sum(1 for c in contexts if c.get('source_type') == self.SOURCE_KB)
        web_count = sum(1 for c in contexts if c.get('source_type') == self.SOURCE_WEB)
        graph_count = sum(1 for c in contexts if c.get('source_type') == self.SOURCE_GRAPH)

        # 判断是否为元问题（关于系统本身的问题）
        meta_keywords = [
            "有哪些文件", "什么文件", "哪些文件", "文件列表", "文件目录",
            "可以查看", "能查看", "有权限", "权限", "能访问", "可以访问",
            "知识库有哪些", "库里有", "文档有哪些", "有哪些文档",
            "系统支持", "系统能", "你能做什么", "你可以做什么",
            "帮助", "使用说明", "怎么用", "如何使用"
        ]
        is_meta_question = any(kw in current_query for kw in meta_keywords)

        # 判断是否需要图谱检索
        need_graph = self._need_graph_search(current_query, contexts)

        # 构建上下文摘要
        context_summary = ""
        if contexts:
            kb_docs = [c['doc'][:200] for c in contexts if c.get('source_type') == self.SOURCE_KB][:2]
            web_docs = [c['doc'][:200] for c in contexts if c.get('source_type') == self.SOURCE_WEB][:2]
            graph_docs = [c['doc'][:200] for c in contexts if c.get('source_type') == self.SOURCE_GRAPH][:2]

            if kb_docs:
                context_summary += f"\n[知识库内容({kb_count}条)]\n" + "\n".join(f"- {d}..." for d in kb_docs)
            if web_docs:
                context_summary += f"\n[网络内容({web_count}条)]\n" + "\n".join(f"- {d}..." for d in web_docs)
            if graph_docs:
                context_summary += f"\n[图谱内容({graph_count}条)]\n" + "\n".join(f"- {d}..." for d in graph_docs)

        prompt = f"""你是一个智能信息检索助手。请分析问题并决定下一步行动。

【用户原始问题】
{original_query}

【当前查询】
{current_query}

【已有信息】
{context_summary if context_summary else "暂无"}

【迭代历史】
已进行 {len(history)} 轮，已检索知识库 {kb_count} 条，网络 {web_count} 条，图谱 {graph_count} 条

【决策选项】

1. **kb_search** - 检索知识库
   - 适用：需要查找知识库中的具体内容、政策、规定等
   - 输出: {{"action": "kb_search"}}

2. **web_search** - 网络搜索
   - 适用：知识库信息不足、需要最新实时信息、需要更权威的来源
   - 输出: {{"action": "web_search", "search_query": "搜索词", "reason": "为什么需要网络搜索"}}

3. **graph_search** - 图谱检索
   - 适用：涉及实体关系、多跳推理、如"XX部门负责什么"、"XX流程包含哪些步骤"
   - 输出: {{"action": "graph_search", "reason": "为什么需要图谱检索"}}

4. **answer** - 生成答案
   - 适用：已有信息足够回答问题
   - 输出: {{"action": "answer", "reason": "信息已足够"}}

5. **rewrite** - 改写查询
   - 适用：查询词不准确、检索结果差
   - 输出: {{"action": "rewrite", "new_query": "改写后的查询", "reason": "为什么改写"}}

6. **decompose** - 分解问题
   - 适用：问题包含多个子问题
   - 输出: {{"action": "decompose", "sub_queries": ["子问题1", "子问题2"], "reason": "为什么分解"}}

【重要决策原则】

1. **元问题识别**（重要！）
   - 如果用户问的是"有哪些文件"、"能查看什么"、"有什么权限"、"知识库包含什么"等关于系统本身的问题
   - 这类问题不需要检索内容，应该直接回答或提供文档列表
   - 如果已有检索结果包含文档来源信息，直接用 answer 生成答案

2. **检索优先级**
   - 首轮优先检索知识库（kb_search）
   - 涉及部门职责、流程步骤、制度关系等问题，优先图谱检索（graph_search）
   - 只有当知识库明显无法回答（如实时信息、外部知识）时才用 web_search

3. **知识库结果评估**（关键！）
   - 如果知识库检索结果已经能回答问题，直接选择 answer
   - 评估标准：检索内容是否包含问题关键词、是否直接相关
   - 不要为了"补充信息"而进行不必要的网络搜索

4. **效率原则**
   - 信息足够时立即 answer，不要浪费轮次
   - 避免重复检索相同内容
   - 如果检索结果已经包含了文档来源信息，可以直接回答元问题

5. **网络搜索谨慎使用**（非常重要！）
   - 网络搜索仅用于：实时信息（天气、新闻）、外部知识、知识库确实没有的内容
   - 内部文档、公司制度、业务流程、薪酬标准等问题绝不应使用网络搜索
   - 如果知识库检索结果能回答问题，就不要使用网络搜索

请输出JSON格式的决策（只输出JSON）:"""

        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500
            )

            content = response.choices[0].message.content.strip()

            # 提取JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            decision = json.loads(content.strip())

            valid_actions = ["answer", "kb_search", "web_search", "graph_search", "rewrite", "decompose"]
            if decision.get("action") not in valid_actions:
                decision = {"action": "kb_search", "reason": "默认检索知识库"}

            return decision

        except Exception as e:
            return {"action": "kb_search", "reason": f"决策解析失败: {str(e)}"}

    def _need_graph_search(self, query: str, contexts: list) -> bool:
        """
        判断是否需要图谱检索

        Args:
            query: 用户查询
            contexts: 已有上下文

        Returns:
            是否需要图谱检索
        """
        if not self.enable_graph or not self.graph_rag:
            return False

        # 使用图谱检索的场景关键词
        graph_keywords = [
            "负责", "管理", "属于", "包含", "相关",
            "哪个部门", "谁负责", "什么流程", "什么条件",
            "审批", "适用", "限额", "标准", "规定",
            "关系", "关联", "流程是什么", "步骤"
        ]

        query_lower = query.lower()
        return any(kw in query_lower for kw in graph_keywords)

    def _is_kb_result_sufficient(self, query: str, docs: list) -> bool:
        """
        评估知识库检索结果是否足够回答问题

        Args:
            query: 用户查询
            docs: 检索到的文档列表

        Returns:
            知识库结果是否足够
        """
        if not docs:
            return False

        # 提取查询关键词
        query_keywords = set()
        stop_words = {"的", "是", "有", "在", "和", "了", "吗", "什么", "怎么", "如何", "哪", "谁", "吗", "呢", "啊"}

        # 分词（简单处理）
        import jieba
        for word in jieba.cut(query):
            word = word.strip()
            if len(word) >= 2 and word not in stop_words:
                query_keywords.add(word)

        if not query_keywords:
            return len(docs) > 0

        # 计算文档与查询的相关性
        matched_count = 0
        for doc in docs[:3]:  # 只看前3个文档
            doc_text = doc.lower() if isinstance(doc, str) else ""
            for keyword in query_keywords:
                if keyword in doc_text:
                    matched_count += 1

        # 如果超过一半的关键词在文档中出现，认为结果足够
        match_ratio = matched_count / len(query_keywords) if query_keywords else 0

        # 判断是否需要网络搜索的问题类型
        web_search_indicators = [
            "今天", "昨天", "最新", "最近", "新闻", "天气",
            "股价", "汇率", "实时", "当前", "现在",
            "2024年", "2025年", "2026年"  # 年份相关的实时信息
        ]
        needs_realtime = any(ind in query for ind in web_search_indicators)

        if needs_realtime:
            return False  # 需要实时信息，知识库不够

        return match_ratio >= 0.5  # 50%以上关键词匹配即可

    def _is_meta_question(self, query: str) -> bool:
        """
        判断是否为元问题（关于知识库本身的问题）

        Args:
            query: 用户查询

        Returns:
            是否为元问题
        """
        meta_patterns = [
            "有哪些文件", "什么文件", "哪些文件", "文件列表", "文件目录",
            "可以查看", "能查看", "有权限查看", "权限查看",
            "能访问", "可以访问", "有权限访问",
            "知识库有哪些", "库里有", "文档有哪些", "有哪些文档",
            "有什么文档", "有什么文件", "包含什么", "包含哪些",
            "你知道什么", "你都知道", "你能回答什么",
            "系统里有什么", "库里有什么"
        ]
        query_lower = query.lower()
        return any(kw in query_lower for kw in meta_patterns)

    def _answer_meta_question(self, query: str, allowed_levels: list = None,
                              role: str = None, department: str = None) -> str:
        """
        回答元问题（关于知识库本身的问题）

        多向量库模式下，遍历用户有权限访问的所有向量库来列出文档。

        Args:
            query: 用户查询
            allowed_levels: 允许访问的安全级别列表
            role: 用户角色（多向量库模式）
            department: 用户部门（多向量库模式）

        Returns:
            回答内容
        """
        try:
            source_map = {}  # {source: {count, levels, pages, collections}}

            # 多向量库模式：遍历用户可访问的所有向量库
            try:
                from knowledge.manager import get_kb_manager
                from auth.gateway import get_accessible_collections as _get_accessible

                kb_mgr = get_kb_manager()
                accessible = _get_accessible(role or 'user', department or '', 'read')

                for kb_name in accessible:
                    coll = kb_mgr.get_collection(kb_name)
                    if not coll:
                        continue
                    try:
                        result = coll.get(include=['metadatas'])
                    except Exception:
                        continue

                    for meta in result.get('metadatas', []):
                        source = meta.get('source', '未知')
                        level = meta.get('security_level', 'public')
                        page = meta.get('page')

                        if source not in source_map:
                            source_map[source] = {
                                'count': 0, 'levels': set(),
                                'pages': set(), 'collections': set()
                            }

                        source_map[source]['count'] += 1
                        source_map[source]['levels'].add(level)
                        source_map[source]['collections'].add(kb_name)
                        if page:
                            source_map[source]['pages'].add(page)

            except ImportError:
                # 降级：单向量库模式
                all_docs = collection.get(include=['metadatas'])
                for meta in all_docs.get('metadatas', []):
                    source = meta.get('source', '未知')
                    level = meta.get('security_level', 'public')
                    page = meta.get('page')

                    if source not in source_map:
                        source_map[source] = {
                            'count': 0, 'levels': set(),
                            'pages': set(), 'collections': set()
                        }

                    source_map[source]['count'] += 1
                    source_map[source]['levels'].add(level)
                    if page:
                        source_map[source]['pages'].add(page)

            # 根据安全级别过滤
            if allowed_levels:
                allowed_set = set(allowed_levels)
                filtered_sources = {}
                for source, info in source_map.items():
                    if info['levels'] & allowed_set:
                        filtered_sources[source] = info
                source_map = filtered_sources

            # 构建回答
            if not source_map:
                return "抱歉，您当前没有权限查看任何文档，或者知识库为空。"

            sorted_sources = sorted(source_map.items(), key=lambda x: x[1]['count'], reverse=True)

            answer_parts = [f"📚 **知识库文档列表**（共 {len(sorted_sources)} 个文档）\n"]

            for i, (source, info) in enumerate(sorted_sources, 1):
                # 显示所属知识库
                colls = info.get('collections', set())
                coll_str = f"，所属: {', '.join(sorted(colls))}" if colls else ""
                pages_str = ''
                if info['pages']:
                    pages_list = sorted(info['pages'])
                    if len(pages_list) <= 5:
                        pages_str = f"，页码: {', '.join(map(str, pages_list))}"
                    else:
                        pages_str = f"，共 {len(info['pages'])} 页"

                answer_parts.append(f"{i}. **{source}** ({info['count']} 条片段{coll_str}{pages_str})")

            answer_parts.append(f"\n**总计**: {sum(s[1]['count'] for s in sorted_sources)} 条知识片段")
            answer_parts.append(f"\n**您的权限级别**: {', '.join(allowed_levels) if allowed_levels else '全部'}")

            answer_parts.append("\n\n💡 **提示**: 您可以直接提问关于这些文档内容的问题，例如：")
            answer_parts.append("\n- 「XX文档中提到的流程是什么？」")
            answer_parts.append("\n- 「出差报销的标准是多少？」")

            return '\n'.join(answer_parts)

        except Exception as e:
            return f"获取文档列表时出错: {str(e)}\n\n您可以直接提问，我会尝试从知识库中检索相关信息。"

    def _graph_search(self, query: str, verbose: bool = True, allowed_levels: list = None) -> list:
        """
        执行图谱检索

        Args:
            query: 用户查询
            verbose: 是否打印详细过程
            allowed_levels: 允许访问的安全级别列表

        Returns:
            检索结果列表
        """
        if not self.graph_rag:
            return []

        try:
            result = self.graph_rag.search(query, top_k=3, verbose=verbose,
                                           allowed_levels=allowed_levels)

            contexts = []
            if result.graph_context:
                contexts.append({
                    'doc': result.graph_context,
                    'meta': {'source': '知识图谱', 'type': 'graph'},
                    'source_type': self.SOURCE_GRAPH,
                    'query': query,
                    'entities': result.entities
                })

            # 同时添加向量检索的结果
            for ctx in result.vector_contexts[:3]:
                contexts.append({
                    'doc': ctx['content'],
                    'meta': ctx['metadata'],
                    'source_type': self.SOURCE_KB,
                    'query': query
                })

            return contexts

        except Exception as e:
            if verbose:
                print(f"图谱检索失败: {e}")
            return []

    def _web_search(self, query: str, top_k: int = 5) -> list:
        """
        网络搜索（使用Serper API）

        Args:
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            [{'title': str, 'link': str, 'snippet': str, 'date': str}, ...]
        """
        if not HAS_SERPER:
            return []

        try:
            url = "https://google.serper.dev/search"
            payload = json.dumps({
                "q": query,
                "gl": "cn",
                "hl": "zh-cn",
                "num": top_k
            })
            headers = {
                'X-API-KEY': SERPER_API_KEY,
                'Content-Type': 'application/json'
            }

            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get('organic', [])[:top_k]:
                results.append({
                    'title': item.get('title', ''),
                    'link': item.get('link', ''),
                    'snippet': item.get('snippet', ''),
                    'date': item.get('date', '')
                })

            return results

        except Exception as e:
            print(f"网络搜索失败: {e}")
            return []

    def _generate_fused_answer(self, query: str, contexts: list, allowed_levels: list = None) -> str:
        """
        生成融合答案 - 智能处理多源信息

        处理策略：
        1. 区分知识库和网络来源
        2. 检测内容冲突
        3. 判断时效性
        4. 智能融合
        5. 权限限制检测
        """
        # 分离不同来源
        kb_contexts = [c for c in contexts if c.get('source_type') == self.SOURCE_KB]
        web_contexts = [c for c in contexts if c.get('source_type') == self.SOURCE_WEB]
        graph_contexts = [c for c in contexts if c.get('source_type') == self.SOURCE_GRAPH]

        # 如果没有任何上下文，检测是否因权限限制
        if not contexts:
            return self._generate_no_context_answer(query, allowed_levels)

        # 如果只有知识库结果且相关性较低，检测是否存在权限限制的相关文档
        if kb_contexts and not web_contexts and allowed_levels:
            # 评估当前知识库结果的相关性
            kb_docs = [c['doc'] for c in kb_contexts]
            if not self._is_kb_result_sufficient(query, kb_docs):
                # 结果不够相关，检查是否存在权限限制的文档
                restricted_info = check_restricted_documents(query, allowed_levels)
                if restricted_info.get("has_restricted"):
                    # 存在超出权限的相关文档，在回答中添加提示
                    levels_str = "、".join(restricted_info["restricted_levels"])
                    sources_str = "、".join(restricted_info["restricted_sources"][:2])

                    # 在上下文中添加权限提示
                    permission_notice = f"""
【重要提示】
检测到与您问题更相关的信息可能存在于「{levels_str}」级别的文档中（如：{sources_str}），但您当前的权限级别无法访问。
以下是根据您可访问的信息生成的回答，可能不够完整或准确：
"""
                    context_str = permission_notice + self._build_context_string(kb_contexts, web_contexts, graph_contexts)

                    # 使用带权限提示的提示词
                    prompt = self._build_answer_prompt_with_permission(query, context_str, levels_str, sources_str, kb_contexts, web_contexts, graph_contexts)

                    try:
                        response = self.client.chat.completions.create(
                            model=MODEL,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.7,
                            max_tokens=2000
                        )
                        return response.choices[0].message.content
                    except Exception as e:
                        return f"生成答案失败: {str(e)}"

        # 正常生成答案
        context_str = self._build_context_string(kb_contexts, web_contexts, graph_contexts)
        prompt = self._build_normal_answer_prompt(query, context_str, kb_contexts, web_contexts, graph_contexts)

        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=2000
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"生成答案失败: {str(e)}"

    def _build_context_string(self, kb_contexts, web_contexts, graph_contexts):
        """构建上下文字符串"""
        kb_parts = []
        for i, c in enumerate(kb_contexts[:5], 1):
            meta = c['meta']
            source_str = meta.get('source', '未知')
            if 'page' in meta:
                source_str += f" 第{meta['page']}页"
            kb_parts.append(f"[知识库-{i}] 来源:{source_str}\n{c['doc']}")

        web_parts = []
        for i, c in enumerate(web_contexts[:5], 1):
            meta = c['meta']
            web_parts.append(f"[网络-{i}] {meta.get('title', '')}\n来源:{meta.get('source', '')}\n{c['doc']}")

        graph_parts = []
        for i, c in enumerate(graph_contexts[:3], 1):
            graph_parts.append(f"[图谱-{i}] {c['doc']}")

        return "\n\n".join(kb_parts + web_parts + graph_parts)

    def _build_normal_answer_prompt(self, query, context_str, kb_contexts, web_contexts, graph_contexts):
        """构建正常回答的提示词"""
        return f"""你是一个严谨的智能助手，需要综合多个信息来源回答问题。

【用户问题】
{query}

【信息来源】
{context_str}

【信息融合原则】

1. **来源优先级**
   - 官方文件、法律法规 > 权威媒体报道 > 普通网页
   - 最新信息 > 过时信息
   - 完整信息 > 片段信息

2. **冲突处理**
   - 如果知识库和网络内容有冲突，明确指出差异
   - 说明可能原因：时效性、适用范围不同等
   - 格式："关于XX，存在不同说法：[来源A]认为...，[来源B]认为..."

3. **时效性判断**
   - 知识库文档可能过时，标注其时间信息
   - 网络信息通常更新，但需验证权威性

4. **来源标注（重要）**
   - 每个关键信息必须标注来源
   - **知识库来源格式**：[文件名 第X页] 或 [文件名]（无页码时）
   - **网络来源格式**：[网站名称] 或 [文章标题]
   - 示例："根据《管理制度汇编》第5页的规定..."、"百度百科显示..."

【回答格式】

### 核心答案
（直接回答问题，整合最可靠的信息）

### 详细说明
（分点展开，每个信息点标注来源）

### 来源汇总
- 知识库：共{len(kb_contexts)}条
- 网络搜索：共{len(web_contexts)}条
- 知识图谱：共{len(graph_contexts)}条

请回答："""

    def _build_answer_prompt_with_permission(self, query, context_str, levels_str, sources_str, kb_contexts, web_contexts, graph_contexts):
        """构建带权限提示的回答提示词"""
        return f"""你是一个严谨的智能助手，需要综合多个信息来源回答问题。

【用户问题】
{query}

【重要提示】
检测到与用户问题更相关的信息可能存在于「{levels_str}」级别的文档中（如：{sources_str}），但用户当前的权限级别无法访问这些文档。
请基于当前可访问的信息回答，并在回答开头明确说明信息可能不完整。

【可访问的信息来源】
{context_str}

【回答要求】

1. **开头说明**
   - 首先明确告知用户：当前回答基于您有权限访问的文档，可能不完整
   - 说明更详细的信息位于「{levels_str}」级别文档中
   - 建议用户如需完整信息，请联系管理员申请相应权限

2. **基于现有信息回答**
   - 如实告知目前可访问文档中的相关内容
   - 如果可访问文档没有相关信息，明确说明"根据您可访问的文档，未找到直接相关信息"

3. **回答格式**

### 权限说明
（说明用户当前权限级别无法访问更完整的信息）

### 基于可访问信息的回答
（基于当前权限可访问的文档回答，或说明无相关信息）

### 来源汇总
- 知识库：共{len(kb_contexts)}条

请回答："""

    def _generate_no_context_answer(self, query: str, allowed_levels: list = None) -> str:
        """
        当没有检索到任何上下文时生成答案

        Args:
            query: 用户问题
            allowed_levels: 用户允许访问的安全级别列表

        Returns:
            回答内容
        """
        # 检测是否存在超出权限的相关文档
        restricted_info = None
        if allowed_levels:
            restricted_info = check_restricted_documents(query, allowed_levels)

        # 如果存在超出权限的相关文档，给出明确提示
        if restricted_info and restricted_info.get("has_restricted"):
            levels_str = "、".join(restricted_info["restricted_levels"])
            sources_str = "、".join(restricted_info["restricted_sources"][:2])

            prompt = f"""用户提问：「{query}」

检测到相关信息存在于您当前权限级别无法访问的文档中。

相关信息：
- 权限级别：{levels_str}
- 可能来源：{sources_str} 等

请生成一个友好且明确的回复，告知用户：
1. 知识库中存在相关信息，但用户当前权限无法访问
2. 相关信息所属的权限级别（{levels_str}）
3. 如需访问，建议联系管理员申请相应权限

回复要简洁专业，不超过100字。"""

            try:
                response = self.client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                    max_tokens=200
                )
                return response.choices[0].message.content
            except Exception as e:
                return f"您好，知识库中存在与您查询相关的信息，但这些信息位于「{levels_str}」级别的文档中，您当前的权限级别无法访问。如需查看，请联系管理员申请相应权限。"

        # 没有权限限制，确实没有相关信息
        prompt = f"""用户提问：「{query}」

很抱歉，我在知识库中没有找到与您问题相关的信息。

请尝试：
1. 换一种方式描述您的问题
2. 使用更具体的关键词
3. 确认您的问题是否与公司文档、制度、流程等相关

如果您想了解知识库中有哪些文档，可以问我「有哪些文件可以查看」。"""

        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"抱歉，知识库中没有找到相关信息。请尝试换一种方式提问，或询问「有哪些文件可以查看」了解知识库内容。"

    def _format_source(self, meta: dict, source_type: str) -> str:
        """格式化来源信息"""
        if source_type == self.SOURCE_WEB:
            return f"{meta.get('title', '网络')} ({meta.get('source', '')})"
        else:
            source_parts = [meta.get('source', '未知文件')]
            if 'page' in meta:
                source_parts.append(f"第{meta['page']}页")
            return " ".join(source_parts)

    def chat_search(
        self,
        query: str,
        history: list = None,
        enable_web_search: bool = True,
        verbose: bool = False
    ) -> dict:
        """
        聊天搜索 - 适用于需要实时信息的对话

        不使用知识库，但可以网络搜索

        Args:
            query: 用户问题
            history: 对话历史
            enable_web_search: 是否启用网络搜索
            verbose: 是否打印详细过程

        Returns:
            {"answer": 回答, "sources": 来源列表}
        """
        contexts = []

        # 判断是否需要网络搜索
        need_web = enable_web_search and self.enable_web_search and self._should_web_search(query)

        if need_web:
            if verbose:
                print(f"[网络搜索] {query}")

            web_results = self._web_search(query)
            for result in web_results:
                contexts.append({
                    'doc': result['snippet'],
                    'meta': {
                        'source': result['link'],
                        'title': result['title'],
                        'date': result.get('date', '')
                    },
                    'source_type': self.SOURCE_WEB,
                    'query': query
                })

            if verbose:
                print(f"   找到 {len(web_results)} 条结果")

        # 生成回答
        if contexts:
            answer = self._generate_fused_answer(query, contexts)
        else:
            # 没有网络搜索结果，直接用 LLM 回答
            answer = self._direct_answer(query, history)

        sources = self._extract_sources(contexts)
        return {
            "answer": answer,
            "sources": sources,
            "web_searched": need_web
        }

    def _should_web_search(self, query: str) -> bool:
        """
        判断是否需要网络搜索

        Args:
            query: 用户查询

        Returns:
            是否需要网络搜索
        """
        # 需要实时信息的场景
        realtime_keywords = [
            "今天", "最新", "今日", "当前", "现在",
            "天气", "新闻", "股价", "行情", "汇率",
            "最近", "近期", "这周", "本月", "今年",
            "实时", "动态", "热点", "发生"
        ]

        query_lower = query.lower()
        return any(kw in query_lower for kw in realtime_keywords)

    def _direct_answer(self, query: str, history: list = None) -> str:
        """
        直接 LLM 回答（无检索）

        Args:
            query: 用户问题
            history: 对话历史

        Returns:
            回答内容
        """
        messages = [
            {"role": "system", "content": "你是一个友好、专业的智能助手。回答简洁明了，不超过200字。"}
        ]

        if history:
            for msg in history[-6:]:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        messages.append({"role": "user", "content": query})

        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.8,
                max_tokens=500
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"抱歉，回答时出现错误: {str(e)}"

    def chat(self):
        """交互模式"""
        print("\n" + "=" * 60)
        print("Agentic RAG 知识库问答系统")
        print("=" * 60)
        print("功能: 知识库检索 + 网络搜索 + 智能融合")
        print("命令:")
        print("  /quit     - 退出")
        print("  /kb <问题>  - 仅知识库检索")
        print("  /web <问题> - 强制网络搜索")
        print("=" * 60)

        while True:
            print("\n" + "-" * 40)
            user_input = input("\n请输入问题: ").strip()

            if not user_input:
                continue

            if user_input == "/quit":
                print("\n再见!")
                break

            if user_input.startswith("/kb "):
                # 仅知识库
                query = user_input[4:]
                self.enable_web_search = False
                result = self.process(query)
                self.enable_web_search = HAS_SERPER
            elif user_input.startswith("/web "):
                # 强制网络搜索
                query = user_input[5:]
                web_results = self._web_search(query)
                contexts = [{
                    'doc': r['snippet'],
                    'meta': {'source': r['link'], 'title': r['title']},
                    'source_type': self.SOURCE_WEB,
                    'query': query
                } for r in web_results]
                result = {
                    'answer': self._generate_fused_answer(query, contexts),
                    'iterations': 1,
                    'contexts': contexts,
                    'sources': self._extract_sources(contexts)
                }
            else:
                result = self.process(user_input)

            print("\n" + "=" * 60)
            print("[答案]")
            print("-" * 40)
            print(result["answer"])

            # 显示来源统计
            sources = result.get('sources', [])
            kb_count = sum(1 for s in sources if s.get('type') == self.SOURCE_KB)
            web_count = sum(1 for s in sources if s.get('type') == self.SOURCE_WEB)
            print(f"\n[来源] 知识库 {kb_count} 条, 网络 {web_count} 条")


# 简化调用接口
def simple_query(query: str, history: list = None) -> dict:
    """
    简化的查询接口，方便其他模块调用

    Args:
        query: 用户问题
        history: 对话历史 [{"role": "user/assistant", "content": "..."}]

    Returns:
        {
            "answer": 回答内容,
            "sources": [{"source": "来源", "snippet": "片段"}]
        }

    使用示例:
        from agentic_rag import simple_query

        result = simple_query("出差补助标准是什么？")
        print(result["answer"])
    """
    agent = AgenticRAG()
    result = agent.process(query, verbose=False, history=history)
    return {
        "answer": result["answer"],
        "sources": result.get("sources", [])
    }


def main():
    """主函数"""
    if collection.count() == 0:
        print("[错误] 知识库为空，请先运行: python rag_demo.py --rebuild")
        return

    args = sys.argv[1:]

    if not args:
        # 交互模式
        agent = AgenticRAG()
        agent.chat()
    else:
        # 单次问答模式
        query = " ".join(args)
        agent = AgenticRAG()
        result = agent.process(query)

        print("\n" + "=" * 60)
        print("[答案]")
        print("-" * 40)
        print(result["answer"])

        # 显示来源统计
        sources = result.get('sources', [])
        kb_count = sum(1 for s in sources if s.get('type') == '知识库')
        web_count = sum(1 for s in sources if s.get('type') == '网络搜索')
        print(f"\n[来源] 知识库 {kb_count} 条, 网络 {web_count} 条")
        print(f"[迭代] {result['iterations']} 轮")


if __name__ == "__main__":
    main()
