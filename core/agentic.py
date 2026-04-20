"""
Agentic RAG - 知识库智能问答系统

核心能力：
1. 知识库检索 - 向量检索 + BM25 + Rerank
2. 网络搜索 - 当知识库不足时自动搜索（需配置SERPER_API_KEY）
3. 图谱检索 - 实体关系推理（需配置Neo4j）
4. 多源融合 - 智能处理知识库和网络内容
5. Agent决策 - 动态决定检索、改写、分解等操作

使用方式：
    from core.agentic import AgenticRAG

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
from core.engine import get_engine

try:
    from config import API_KEY, BASE_URL, MODEL
except ImportError:
    pass

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

# 导入查询分类器
try:
    from core.query_classifier import QueryClassifier, QueryType
    HAS_CLASSIFIER = True
except ImportError:
    HAS_CLASSIFIER = False
    QueryType = None


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

        # 初始化查询分类器
        self.query_classifier = QueryClassifier() if HAS_CLASSIFIER else None

        # 初始化置信度门控
        try:
            from core.confidence_gate import create_gate
            self.confidence_gate = create_gate()
        except ImportError:
            self.confidence_gate = None

        # 初始化多维质量评估器
        try:
            from core.quality_assessor import create_assessor
            self.quality_assessor = create_assessor()
        except ImportError:
            self.quality_assessor = None

        # 初始化推理反思器
        try:
            from core.reasoning_reflector import create_reflector
            self.reasoning_reflector = create_reflector()
        except ImportError:
            self.reasoning_reflector = None

        # 初始化循环防护器
        try:
            from core.loop_guard import create_guard
            self.loop_guard = create_guard(max_iterations=max_iterations)
        except ImportError:
            self.loop_guard = None

        # Context Compression 配置
        self.MAX_CONTEXT_TOKENS = 3500  # 最大上下文 token 数（模型窗口 * 0.35）
        self.MAX_CONTEXT_COUNT = 20     # 最大上下文数量
        self.RERANK_THRESHOLD = 0.3    # Rerank 过滤阈值

        # Answer Grounding 配置
        self.MAX_GROUNDING_RETRY = 1   # 幻觉修正最多重试 1 次
        self.grounding_retry_count = 0

    def should_rewrite(self, query: str, history: list = None) -> bool:
        """
        判断是否需要重写查询

        触发条件：
        1. 有历史对话 → 强制改写（消歧）
        2. 短查询（< 10 字符）→ 强制改写（扩展）
        3. 其他情况 → LLM 判断

        Args:
            query: 用户问题
            history: 对话历史

        Returns:
            bool: 是否需要重写
        """
        # 条件 1: 有历史对话，强制改写（消歧）
        if history and len(history) > 0:
            return True

        # 条件 2: 短查询，强制改写（扩展）
        if len(query) < 10:
            return True

        # 条件 3: LLM 判断是否需要改写
        try:
            prompt = f"""判断以下问题是否需要重写以获得更好的检索效果。
问题：{query}

需要重写的情况：
- 包含代词（它、这个、那个）指代不清
- 过于口语化
- 缺少关键上下文

不需要重写的情况：
- 问题清晰完整
- 包含具体的专业术语
- 可以直接检索

请只回答 "需要" 或 "不需要"："""

            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10
            )
            answer = response.choices[0].message.content.strip()
            return "需要" in answer
        except Exception:
            # 出错时默认不重写
            return False

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

        # ==================== 统一 Query Rewriting 入口 ====================
        original_query = query
        if self.should_rewrite(query, history):
            rewritten = self._rewrite_query(query, history, strategy="all")
            if verbose:
                print(f"\n[查询重写] {query} → {rewritten}")
            emit_log("rewrite", {
                "original": query,
                "rewritten": rewritten
            })
            query = rewritten  # 使用重写后的查询

        # ==================== 新增：查询分类 ====================
        classified = None
        if self.query_classifier:
            classified = self.query_classifier.classify(query, history)
            emit_log("classify", {
                "query_type": classified.query_type.value,
                "skip_llm": classified.skip_llm_decision,
                "keywords": classified.keywords,
                "confidence": classified.confidence
            })

            if verbose:
                print(f"\n[分类] 类型: {classified.query_type.value}, 跳过LLM: {classified.skip_llm_decision}")
                if classified.keywords:
                    print(f"   关键词: {', '.join(classified.keywords[:5])}")

        # ==================== 元问题直接处理 ====================
        if classified and classified.query_type == QueryType.META:
            if verbose:
                print("\n[元问题] 检测到关于知识库本身的问题")
            emit_log("decision", {"action": "meta_query", "reason": "分类器识别为元问题"})

            answer = self._answer_meta_question(query, allowed_levels, role=role, department=department)
            emit_log("answer", {"reason": "元问题直接回答"})

            return {
                "answer": answer,
                "iterations": 0,
                "reasoning": [{"type": "meta_question", "query": query, "classified": True}],
                "contexts": [],
                "sources": [],
                "log_trace": log_trace,
                "classified": classified.to_dict() if classified else None
            }

        # ==================== 实时信息走网络搜索 ====================
        if classified and classified.query_type == QueryType.REALTIME:
            if verbose:
                print("\n[实时信息] 检测到需要实时信息，执行网络搜索")
            emit_log("decision", {"action": "web_search", "reason": "分类器识别为实时信息"})

            return self._web_search_flow(query, log_trace, emit_log, verbose, classified)

        # ==================== 兼容旧版：无分类器时的元问题检测 ====================
        if not classified and self._is_meta_question(query):
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
                "log_trace": log_trace,
                "classified": None
            }

        # ==================== 知识库检索流程 ====================
        # 获取检索配置
        if classified:
            search_config = classified.search_config
            max_iterations = search_config.get("max_iterations", self.max_iterations)
            top_k = search_config.get("top_k", 5)
        else:
            max_iterations = self.max_iterations
            top_k = 5

        # 知识问答流程
        all_contexts = []
        reasoning_trace = []
        current_query = classified.processed_query if classified else query
        iteration = 0

        if verbose:
            print("\n[开始检索...]")

        # ==================== 简单查询：直接检索，跳过 LLM 决策 ====================
        if classified and classified.skip_llm_decision:
            if verbose:
                print(f"[直接检索] {current_query}")

            # 提取 source_filter（如果是文件特定查询）
            source_filter = None
            if classified and hasattr(classified, 'source_filter'):
                source_filter = classified.source_filter

            # 如果是图片查询且指定了文件名，直接从向量库获取图片
            if (classified and classified.query_type == QueryType.FILE_SPECIFIC and
                source_filter and ("图片" in query or "图像" in query or "image" in query.lower() or "figure" in query.lower())):
                direct_images = self._get_images_for_source(source_filter, collections)
                if direct_images:
                    if verbose:
                        print(f"   [图片查询] 从 {source_filter} 找到 {len(direct_images)} 张图片")

                    return {
                        "answer": f"在文件 **{source_filter}** 中找到 **{len(direct_images)}** 张图片。\n\n图片列表：\n" +
                                  "\n".join([f"- 第{img.get('page', '?')}页: {img.get('id')}" for img in direct_images[:10]]),
                        "iterations": 0,
                        "reasoning": [{"type": "direct_image_query", "source": source_filter}],
                        "contexts": [],
                        "sources": [{"source": source_filter, "type": self.SOURCE_KB, "count": len(direct_images)}],
                        "log_trace": log_trace,
                        "classified": classified.to_dict() if classified else None,
                        "images": direct_images,
                        "tables": [],
                        "sections": []
                    }

            search_start = time.time()
            results = get_engine().search_knowledge(
                current_query,
                top_k=top_k,
                allowed_levels=allowed_levels,
                role=role,
                department=department,
                collections=collections,
                source_filter=source_filter  # 添加 source_filter 参数
            )
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
                "skip_llm_decision": True
            })

            if verbose:
                print(f"   找到 {len(docs)} 个片段")

            # ==================== 置信度门控检查 ====================
            gate_result = self._check_confidence_gate(current_query, docs, verbose)
            if gate_result and gate_result.action.value != "pass":
                # 触发补救流程
                remediation_result = self._remediation_flow(
                    query, current_query, all_contexts, gate_result,
                    allowed_levels, role, department, collections,
                    verbose, log_trace, emit_log
                )
                if remediation_result:
                    return remediation_result

            # ==================== 多维质量评估 ====================
            quality_assessment = self._assess_quality(current_query, docs, metas, verbose)
            # 质量评估结果可用于后续决策，暂时只记录

            # ==================== Context Compression ====================
            all_contexts = self._compress_contexts(query, all_contexts)

            # 直接生成答案
            answer = self._generate_fused_answer(query, all_contexts, allowed_levels)

            # ==================== Answer Grounding 闭环 ====================
            # 重置 grounding 重试计数
            self.grounding_retry_count = 0
            answer = self._verify_and_refine_answer(query, answer, all_contexts)

            # ==================== 推理反思 ====================
            reflection = self._reflect_on_answer(query, answer, all_contexts, verbose)

            sources = self._extract_sources(all_contexts)
            # 只从相关来源提取图片（传入原始查询以提取特定文件名）
            source_names = [s.get("source") for s in sources if s.get("source")]
            rich_media = self._extract_rich_media(all_contexts, sources_filter=source_names, original_query=query)

            return {
                "answer": answer,
                "iterations": 1,
                "reasoning": [{"type": "direct_search", "query": current_query, "classified": classified.to_dict()}],
                "contexts": all_contexts,
                "sources": sources,
                "log_trace": log_trace,
                "classified": classified.to_dict() if classified else None,
                # 富媒体信息
                "images": rich_media["images"],
                "tables": rich_media["tables"],
                "sections": rich_media["sections"]
            }

        # ==================== 复杂查询：迭代决策流程 ====================
        # 对于 FACT/COMPARISON/PROCESS 类型，强制首轮知识库检索
        # 这确保即使 LLM 决策错误，也能有检索结果作为基础
        need_initial_search = (
            classified and
            classified.query_type in (QueryType.FACT, QueryType.COMPARISON, QueryType.PROCESS) and
            not all_contexts  # 还没有检索过
        )

        if need_initial_search:
            if verbose:
                print(f"[强制首轮检索] {current_query}")

            # 提取 source_filter（如果是文件特定查询）
            source_filter = None
            if hasattr(classified, 'source_filter'):
                source_filter = classified.source_filter

            search_start = time.time()
            results = get_engine().search_knowledge(
                current_query,
                top_k=top_k,
                allowed_levels=allowed_levels,
                role=role,
                department=department,
                collections=collections,
                source_filter=source_filter
            )
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
                "phase": "initial_mandatory"
            })

            if verbose:
                print(f"   找到 {len(docs)} 个片段")

            # 记录到循环防护
            if self.loop_guard and docs:
                from core.confidence_gate import check_confidence
                gate_result = check_confidence(current_query, docs)
                self.loop_guard.record_iteration(
                    query=current_query,
                    confidence=gate_result.top_score if gate_result else 0.5,
                    results_count=len(docs)
                )

        while iteration < max_iterations:
            iteration += 1
            iter_start = time.time()

            # ==================== 循环防护检查 ====================
            if self.loop_guard:
                from core.loop_guard import GuardDecision
                guard_result = self.loop_guard.should_continue()
                if guard_result.decision != GuardDecision.CONTINUE:
                    if verbose:
                        print(f"\n[循环防护] 🛑 {guard_result.decision.value}")
                        print(f"   原因: {guard_result.reason}")
                        print(f"   建议: {guard_result.recommendation}")
                    # 生成当前最佳答案
                    break

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
                # ==================== Context Compression ====================
                all_contexts = self._compress_contexts(query, all_contexts)

                # 生成答案
                answer_start = time.time()
                answer = self._generate_fused_answer(query, all_contexts, allowed_levels)
                answer_duration = (time.time() - answer_start) * 1000

                emit_log("answer", {
                    "duration_ms": round(answer_duration, 0),
                    "total_duration_ms": round((time.time() - start_time) * 1000, 0)
                })

                # ==================== Answer Grounding 闭环 ====================
                self.grounding_retry_count = 0
                answer = self._verify_and_refine_answer(query, answer, all_contexts)

                # ==================== 推理反思 ====================
                reflection = self._reflect_on_answer(query, answer, all_contexts, verbose)

                sources = self._extract_sources(all_contexts)
                # 只从相关来源提取图片（传入原始查询以提取特定文件名）
                source_names = [s.get("source") for s in sources if s.get("source")]
                rich_media = self._extract_rich_media(all_contexts, sources_filter=source_names, original_query=query)
                return {
                    "answer": answer,
                    "iterations": iteration,
                    "reasoning": reasoning_trace,
                    "contexts": all_contexts,
                    "sources": sources,
                    "log_trace": log_trace,
                    "classified": classified.to_dict() if classified else None,
                    # 富媒体信息
                    "images": rich_media["images"],
                    "tables": rich_media["tables"],
                    "sections": rich_media["sections"]
                }

            elif decision["action"] == "kb_search":
                # 知识库检索
                search_start = time.time()
                if verbose:
                    print(f"[知识库检索] {current_query}")

                # 提取 source_filter（如果是文件特定查询）
                source_filter = None
                if classified and hasattr(classified, 'source_filter'):
                    source_filter = classified.source_filter

                results = get_engine().search_knowledge(current_query, top_k=top_k, allowed_levels=allowed_levels,
                                           role=role, department=department, collections=collections,
                                           source_filter=source_filter)
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

                # ==================== 置信度门控检查 ====================
                gate_result = self._check_confidence_gate(current_query, docs, verbose)
                if gate_result and gate_result.action.value != "pass":
                    # 触发补救流程
                    remediation_result = self._remediation_flow(
                        query, current_query, all_contexts, gate_result,
                        allowed_levels, role, department, collections,
                        verbose, log_trace, emit_log
                    )
                    if remediation_result:
                        return remediation_result

                # ==================== 多维质量评估 ====================
                quality_assessment = self._assess_quality(current_query, docs, metas, verbose)

                # ==================== 记录迭代信息（循环防护）====================
                if self.loop_guard and quality_assessment:
                    from core.confidence_gate import check_confidence
                    gate_result = check_confidence(current_query, docs)
                    self.loop_guard.record_iteration(
                        query=current_query,
                        confidence=gate_result.top_score if gate_result else 0.5,
                        results_count=len(docs)
                    )

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
                kb_count = sum(1 for c in all_contexts if c.get('source_type') == self.SOURCE_KB)
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
                    results = get_engine().search_knowledge(sub_q, top_k=3, allowed_levels=allowed_levels,
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

        # ==================== Context Compression ====================
        all_contexts = self._compress_contexts(query, all_contexts)

        answer = self._generate_fused_answer(query, all_contexts, allowed_levels)
        sources = self._extract_sources(all_contexts)
        # 只从相关来源提取图片（传入原始查询以提取特定文件名）
        source_names = [s.get("source") for s in sources if s.get("source")]
        rich_media = self._extract_rich_media(all_contexts, sources_filter=source_names, original_query=query)

        emit_log("complete", {
            "total_duration_ms": round((time.time() - start_time) * 1000, 0)
        })

        return {
            "answer": answer,
            "iterations": iteration,
            "reasoning": reasoning_trace,
            "contexts": all_contexts,
            "sources": sources,
            "log_trace": log_trace,
            "classified": classified.to_dict() if classified else None,
            # 富媒体信息
            "images": rich_media["images"],
            "tables": rich_media["tables"],
            "sections": rich_media["sections"]
        }

    def _web_search_flow(self, query: str, log_trace: list, emit_log, verbose: bool,
                         classified=None) -> dict:
        """
        网络搜索流程

        Args:
            query: 用户查询
            log_trace: 日志追踪列表
            emit_log: 日志发送函数
            verbose: 是否打印详细过程
            classified: 分类结果

        Returns:
            响应字典
        """
        import time

        if not self.enable_web_search:
            # 网络搜索未启用，返回提示
            return {
                "answer": "抱歉，网络搜索功能未启用，无法获取实时信息。",
                "iterations": 0,
                "reasoning": [{"type": "web_search_disabled"}],
                "contexts": [],
                "sources": [],
                "log_trace": log_trace,
                "classified": classified.to_dict() if classified else None
            }

        web_results = self._web_search(query)

        contexts = []
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

        emit_log("retrieve", {
            "source": "网络搜索",
            "query": query,
            "count": len(web_results)
        })

        if verbose:
            print(f"   找到 {len(web_results)} 条网络结果")

        # ==================== Context Compression ====================
        contexts = self._compress_contexts(query, contexts)

        answer = self._generate_fused_answer(query, contexts)
        sources = self._extract_sources(contexts)
        # 只从相关来源提取图片（传入原始查询以提取特定文件名）
        source_names = [s.get("source") for s in sources if s.get("source")]
        rich_media = self._extract_rich_media(contexts, sources_filter=source_names, original_query=query)

        return {
            "answer": answer,
            "iterations": 1,
            "reasoning": [{"type": "web_search", "query": query}],
            "contexts": contexts,
            "sources": sources,
            "log_trace": log_trace,
            "classified": classified.to_dict() if classified else None,
            # 富媒体信息
            "images": rich_media["images"],
            "tables": rich_media["tables"],
            "sections": rich_media["sections"]
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

    def _get_images_for_source(self, source: str, collections: list = None) -> list:
        """
        直接从向量库获取指定文件的所有图片

        当用户查询特定文件的图片时，直接查询向量库获取该文件的所有图片信息，
        而不是依赖于检索结果的 contexts。

        Args:
            source: 文件名（如 "2604.09205v1.pdf"）
            collections: 要查询的向量库列表（默认为 ['public_kb']）

        Returns:
            图片信息列表 [{"id": "...", "caption": "...", "url": "...", "page": 1, "source": "..."}]
        """
        try:
            from knowledge.manager import get_kb_manager
            kb_mgr = get_kb_manager()
        except ImportError:
            return []

        images = []
        seen_ids = set()

        # 确定要查询的向量库
        target_collections = collections or ['public_kb']

        for kb_name in target_collections:
            try:
                coll = kb_mgr.get_collection(kb_name)
                if not coll:
                    continue

                # 查询该文件的所有文档
                result = coll.get(
                    where={'source': source},
                    include=['metadatas']
                )

                for meta in result.get('metadatas', []):
                    images_json = meta.get('images_json')
                    if images_json:
                        try:
                            imgs = json.loads(images_json)
                            for img in imgs:
                                img_id = img.get('id')
                                if img_id and img_id not in seen_ids:
                                    seen_ids.add(img_id)
                                    images.append({
                                        "id": img_id,
                                        "caption": img.get("caption", ""),
                                        "url": f"/images/{img_id}",
                                        "page": img.get("page") or meta.get("page"),
                                        "source": source,
                                        "width": img.get("width"),
                                        "height": img.get("height")
                                    })
                        except (json.JSONDecodeError, TypeError):
                            pass
            except Exception as e:
                print(f"[警告] 从 {kb_name} 获取图片失败: {e}")
                continue

        return images

    def _extract_rich_media(self, contexts: list, sources_filter: list = None, max_images: int = 10,
                            original_query: str = None) -> dict:
        """
        从检索结果提取富媒体信息

        Args:
            contexts: 检索上下文列表
            sources_filter: 来源过滤列表（只返回这些来源的媒体）
            max_images: 最大返回图片数
            original_query: 原始用户查询（用于提取特定文件名）

        Returns:
            {"images": [...], "tables": [...], "sections": [...]}
        """
        import json
        images = []
        tables = []
        sections = set()
        seen_image_ids = set()  # 去重

        # 从用户查询中提取特定文件名（如 "2604.09205v1.pdf中有几张图片"）
        specific_source = None
        if original_query:
            import re
            # 匹配文件名模式：xxx.pdf, xxx.docx, xxx.xlsx 等
            file_pattern = r'([^\s，。？!！?？]+?\.(?:pdf|docx?|xlsx?|txt|md))'
            match = re.search(file_pattern, original_query, re.IGNORECASE)
            if match:
                specific_source = match.group(1)

        # 如果用户查询指定了特定文件，优先使用该文件名过滤
        effective_filter = sources_filter
        if specific_source:
            effective_filter = [specific_source]

        # 构建来源过滤集合（支持模糊匹配：source_filter 包含 source 即可）
        # 例如: "2604.09205v1.pdf (第6页)" 应匹配 "2604.09205v1.pdf"
        def source_matches(source, filter_list):
            if not filter_list:
                return True
            for f in filter_list:
                # 双向匹配：filter 包含 source 或 source 包含 filter 的文件名部分
                # 提取文件名部分（去掉页码等信息）
                f_clean = f.split('(')[0].strip()
                if source in f or f_clean in source or source in f_clean:
                    return True
            return False

        for ctx in contexts:
            meta = ctx.get("meta", {})
            source = meta.get("source", "")

            # 如果有来源过滤，只处理匹配的来源
            if effective_filter and not source_matches(source, effective_filter):
                continue

            # 提取图片（支持 images_json 和 images 两种格式）
            images_data = None
            if meta.get("images_json"):
                try:
                    images_data = json.loads(meta["images_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            elif meta.get("images"):
                images_data = meta["images"]

            if images_data:
                for img in images_data:
                    img_id = img.get("id")
                    if img_id and img_id not in seen_image_ids:
                        seen_image_ids.add(img_id)
                        images.append({
                            "id": img_id,
                            "caption": img.get("caption", ""),
                            "url": f"/images/{img_id}",
                            "page": meta.get("page"),
                            "source": meta.get("source"),
                            "width": img.get("width"),
                            "height": img.get("height")
                        })

            # 提取表格
            if meta.get("is_table") or meta.get("chunk_type") == "table":
                tables.append({
                    "id": meta.get("id", ""),
                    "markdown": ctx.get("doc", "")[:1000],  # 截取部分
                    "page": meta.get("page"),
                    "source": meta.get("source")
                })

            # 提取章节
            if meta.get("section_path"):
                sections.add(meta["section_path"])

        # 限制图片数量
        images = images[:max_images]

        return {
            "images": images,
            "tables": tables,
            "sections": list(sections)
        }

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
            "帮助", "使用说明", "怎么用", "如何使用",
            # 新增：向量库名称相关
            "public_kb", "dept_tech", "dept_hr", "dept_finance", "dept_operation",
            "kb里", "向量库", "有哪些库", "库列表", "kb有哪些"
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

    def _check_confidence_gate(self, query: str, docs: list, verbose: bool = True):
        """
        检查检索结果的置信度

        Args:
            query: 用户查询
            docs: 检索到的文档列表
            verbose: 是否打印详细日志

        Returns:
            GateResult 或 None（如果门控未启用）
        """
        if not self.confidence_gate or not docs:
            return None

        try:
            gate_result = self.confidence_gate.evaluate(query, docs)

            if verbose:
                action_emoji = {
                    "pass": "✅",
                    "rewrite": "🔄",
                    "web_search": "🌐",
                    "fallback": "⚠️"
                }.get(gate_result.action.value, "❓")

                print(f"   [置信度门控] {action_emoji} {gate_result.action.value}")
                print(f"      Top-1 分数: {gate_result.top_score:.3f}")
                print(f"      决策原因: {gate_result.reason}")

            return gate_result

        except Exception as e:
            if verbose:
                print(f"   [置信度门控] ⚠️ 评估失败: {e}")
            return None

    def _assess_quality(self, query: str, docs: list, metas: list = None,
                        verbose: bool = True):
        """
        多维质量评估

        Args:
            query: 用户查询
            docs: 检索到的文档列表
            metas: 文档元数据
            verbose: 是否打印详细日志

        Returns:
            QualityAssessment 或 None（如果评估器未启用）
        """
        if not self.quality_assessor or not docs:
            return None

        try:
            assessment = self.quality_assessor.assess(query, docs, metas)

            if verbose:
                status = "✅ 达标" if assessment.is_sufficient else "⚠️ 未达标"
                print(f"   [质量评估] {status}")
                print(f"      相关性: {assessment.relevance.score}/10")
                print(f"      完整性: {assessment.completeness.score}/10")
                print(f"      准确性: {assessment.accuracy.score}/10")
                print(f"      覆盖率: {assessment.coverage.score}/10")
                print(f"      总分: {assessment.total_score}/40 (阈值: 32)")

                # 收集各维度的问题
                all_issues = []
                for dim in [assessment.relevance, assessment.completeness,
                           assessment.accuracy, assessment.coverage]:
                    all_issues.extend(dim.issues or [])
                if all_issues:
                    print(f"      问题: {', '.join(all_issues[:3])}")

            return assessment

        except Exception as e:
            if verbose:
                print(f"   [质量评估] ⚠️ 评估失败: {e}")
            return None

    def _reflect_on_answer(self, query: str, answer: str, contexts: list,
                           verbose: bool = True):
        """
        推理反思：检查答案中的未验证声明

        Args:
            query: 用户查询
            answer: 生成的答案
            contexts: 检索上下文
            verbose: 是否打印详细日志

        Returns:
            ReflectionResult 或 None
        """
        if not self.reasoning_reflector or not answer:
            return None

        try:
            # 提取上下文文本
            context_texts = [c.get('doc', '') for c in contexts if c.get('doc')]

            reflection = self.reasoning_reflector.reflect(query, answer, context_texts)

            if verbose:
                status = "🔍 需验证" if reflection.has_unverified_claims else "✅ 已验证"
                print(f"   [推理反思] {status}")
                print(f"      声明总数: {len(reflection.claims)}")
                print(f"      未验证声明: {len(reflection.unverified_claims)}")
                print(f"      总结: {reflection.reflection_summary}")

                if reflection.verification_queries:
                    print(f"      建议查询: {reflection.verification_queries[0][:50]}...")

            return reflection

        except Exception as e:
            if verbose:
                print(f"   [推理反思] ⚠️ 反思失败: {e}")
            return None

    def _remediation_flow(self, original_query: str, current_query: str,
                          all_contexts: list, gate_result,
                          allowed_levels: list, role: str, department: str,
                          collections: list, verbose: bool, log_trace: list,
                          emit_log) -> dict:
        """
        补救流程：处理低置信度检索结果

        根据门控决策触发不同的补救措施：
        - REWRITE: 尝试查询重写后重新检索
        - WEB_SEARCH: 触发网络搜索
        - FALLBACK: 直接返回降级回答

        Args:
            original_query: 原始用户查询
            current_query: 当前处理的查询
            all_contexts: 已收集的上下文
            gate_result: 门控评估结果
            allowed_levels: 允许的权限级别
            role: 用户角色
            department: 用户部门
            collections: 目标向量库列表
            verbose: 是否打印详细日志
            log_trace: 日志追踪列表
            emit_log: 日志发送函数

        Returns:
            dict: 补救结果（如果有），否则返回 None 继续正常流程
        """
        from core.confidence_gate import GateAction

        action = gate_result.action
        emit_log("remediation", {
            "action": action.value,
            "confidence": gate_result.confidence,
            "reason": gate_result.reason
        })

        if action == GateAction.WEB_SEARCH:
            # 触发网络搜索
            if not self.enable_web_search:
                if verbose:
                    print("   [补救] 网络搜索未启用，跳过")
                return None

            if verbose:
                print(f"   [补救] 触发网络搜索...")

            search_query = current_query
            web_results = self._web_search(search_query)

            if web_results:
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

                if verbose:
                    print(f"      网络搜索找到 {len(web_results)} 条结果")

                # ==================== Context Compression ====================
                all_contexts = self._compress_contexts(original_query, all_contexts)

                # 返回融合后的结果
                answer = self._generate_fused_answer(original_query, all_contexts, allowed_levels)
                sources = self._extract_sources(all_contexts)
                source_names = [s.get("source") for s in sources if s.get("source")]
                rich_media = self._extract_rich_media(all_contexts, sources_filter=source_names, original_query=original_query)

                return {
                    "answer": answer,
                    "iterations": 1,
                    "reasoning": [{
                        "type": "remediation_web_search",
                        "trigger": gate_result.reason,
                        "query": search_query,
                        "results_count": len(web_results)
                    }],
                    "contexts": all_contexts,
                    "sources": sources,
                    "log_trace": log_trace,
                    "classified": None,
                    "images": rich_media["images"],
                    "tables": rich_media["tables"],
                    "sections": rich_media["sections"]
                }
            else:
                if verbose:
                    print("      网络搜索无结果")
                return None

        elif action == GateAction.REWRITE:
            # 查询重写（简化实现：提取关键词重新检索）
            if verbose:
                print(f"   [补救] 尝试查询重写...")

            # 使用 LLM 重写查询
            rewritten_query = self._rewrite_query(current_query)

            if rewritten_query and rewritten_query != current_query:
                if verbose:
                    print(f"      重写后查询: {rewritten_query}")

                # 重新检索
                results = get_engine().search_knowledge(
                    rewritten_query,
                    top_k=5,
                    allowed_levels=allowed_levels,
                    role=role,
                    department=department,
                    collections=collections
                )
                docs = results.get('documents', [[]])[0]
                metas = results.get('metadatas', [[]])[0]

                if docs:
                    # 检查重写后的置信度
                    new_gate_result = self.confidence_gate.evaluate(rewritten_query, docs)

                    if new_gate_result.top_score > gate_result.top_score:
                        # 置信度提升，使用新结果
                        if verbose:
                            print(f"      置信度提升: {gate_result.top_score:.3f} → {new_gate_result.top_score:.3f}")

                        for doc, meta in zip(docs, metas):
                            all_contexts.append({
                                'doc': doc,
                                'meta': meta,
                                'source_type': self.SOURCE_KB,
                                'query': rewritten_query
                            })

                        # ==================== Context Compression ====================
                        all_contexts = self._compress_contexts(original_query, all_contexts)

                        # 返回融合后的结果
                        answer = self._generate_fused_answer(original_query, all_contexts, allowed_levels)
                        sources = self._extract_sources(all_contexts)
                        source_names = [s.get("source") for s in sources if s.get("source")]
                        rich_media = self._extract_rich_media(all_contexts, sources_filter=source_names, original_query=original_query)

                        return {
                            "answer": answer,
                            "iterations": 1,
                            "reasoning": [{
                                "type": "remediation_rewrite",
                                "original_query": current_query,
                                "rewritten_query": rewritten_query,
                                "confidence_improvement": new_gate_result.top_score - gate_result.top_score
                            }],
                            "contexts": all_contexts,
                            "sources": sources,
                            "log_trace": log_trace,
                            "classified": None,
                            "images": rich_media["images"],
                            "tables": rich_media["tables"],
                            "sections": rich_media["sections"]
                        }
                    else:
                        if verbose:
                            print(f"      置信度未提升，保持原结果")

            return None  # 重写未改善，继续正常流程

        elif action == GateAction.FALLBACK:
            # 降级处理
            if verbose:
                print("   [补救] 无检索结果，返回降级回答")

            return {
                "answer": "抱歉，我在知识库中没有找到相关信息。请尝试：\n\n"
                          "1. **换一种方式提问** - 使用更具体的描述\n"
                          "2. **提供更多上下文** - 告诉我相关的背景信息\n"
                          "3. **检查关键词** - 确保使用了正确的术语",
                "iterations": 0,
                "reasoning": [{
                    "type": "fallback",
                    "reason": gate_result.reason
                }],
                "contexts": [],
                "sources": [],
                "log_trace": log_trace,
                "classified": None,
                "images": [],
                "tables": [],
                "sections": []
            }

        return None  # 默认继续正常流程

    def _rewrite_query(self, query: str, history: list = None,
                       strategy: str = "professional") -> str:
        """
        增强版查询重写：将口语化表达转为专业术语

        Args:
            query: 原始查询
            history: 对话历史（用于实体补全）
            strategy: 重写策略
                - professional: 口语化→专业术语
                - expand: 扩展关键词
                - clarify: 消歧义
                - entity: 实体补全

        Returns:
            str: 重写后的查询
        """
        # 尝试多种策略组合
        rewritten = query

        # 策略1: 口语化→专业术语映射
        if strategy in ["professional", "all"]:
            rewritten = self._apply_professional_mapping(rewritten)

        # 策略2: 实体补全（利用对话历史）
        if strategy in ["entity", "all"] and history:
            rewritten = self._complete_entities(rewritten, history)

        # 策略3: LLM 深度重写（仅在需要时调用）
        if strategy in ["professional", "all"]:
            llm_rewritten = self._llm_rewrite(rewritten)
            if llm_rewritten and len(llm_rewritten) > len(rewritten) * 0.5:
                rewritten = llm_rewritten

        return rewritten

    def _apply_professional_mapping(self, query: str) -> str:
        """
        应用口语化→专业术语映射

        常见的企业文档场景术语映射
        """
        # 术语映射表（可根据实际场景扩展）
        TERM_MAPPING = {
            # 通用业务术语
            "报销": "差旅报销 费用报销 报销审批",
            "请假": "休假申请 请假审批 考勤管理",
            "加班": "加班申请 工时管理 加班审批",
            "工资": "薪酬管理 工资发放 薪资结构",
            "合同": "合同管理 合同签署 合同审批",
            "流程": "审批流程 业务流程 工作流",
            "制度": "管理制度 规章制度 企业规范",
            "规定": "管理规定 制度规定 政策要求",

            # 时间相关
            "几天": "时限 审批时限 办理时限",
            "多久": "处理时效 审批周期 办理周期",

            # 数量相关
            "多少": "标准 额度 限额 标准",
            "能不能": "是否允许 是否可以 权限",

            # 部门相关
            "人事": "人力资源 HR 人力部门",
            "财务": "财务部 财务部门 财务管理",
            "技术": "技术部 研发部 IT部门",
        }

        result = query
        for colloquial, professional in TERM_MAPPING.items():
            if colloquial in query:
                # 不替换，而是扩展
                result = result.replace(colloquial, f"{colloquial} {professional.split()[0]}")

        return result

    def _complete_entities(self, query: str, history: list) -> str:
        """
        实体补全：利用对话历史补充缺失的实体

        例如：
        - 用户："标准是多少？"（缺少主语）
        - 上一轮："出差报销有什么规定？"
        - 补全后："出差报销标准是多少？"
        """
        if not history:
            return query

        # 获取最近用户消息
        last_user_msg = None
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        if not last_user_msg:
            return query

        # 检查当前查询是否缺少主语
        BUSINESS_KEYWORDS = ["报销", "出差", "请假", "工资", "合同", "审批", "流程",
                           "制度", "规定", "标准", "金额", "时间"]

        has_subject = any(kw in query for kw in BUSINESS_KEYWORDS)

        if not has_subject:
            # 从上一轮提取实体
            try:
                import jieba
                entities = []
                for word in jieba.cut(last_user_msg):
                    word = word.strip()
                    if len(word) >= 2 and any(kw in word for kw in BUSINESS_KEYWORDS):
                        entities.append(word)

                if entities:
                    # 补全实体
                    return f"{entities[0]} {query}"
            except ImportError:
                pass

        return query

    def _llm_rewrite(self, query: str) -> str:
        """
        使用 LLM 进行深度查询重写
        """
        try:
            prompt = f"""请将以下用户查询重写为更专业、更精确的搜索查询。

原始查询: {query}

重写要求:
1. 保留核心意图
2. 使用专业术语替换口语化表达
3. 补充可能遗漏的关键词
4. 保持简洁，不要添加解释

请直接输出重写后的查询，不要有任何前缀或解释。"""

            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=100
            )

            rewritten = response.choices[0].message.content.strip()
            return rewritten

        except Exception as e:
            print(f"[警告] LLM 查询重写失败: {e}")
            return query

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
            # 新增：更多权限相关表达
            "我的权限", "用户权限", "查看权限", "访问权限",
            "权限能", "权限可以", "有什么权限", "有哪些权限",
            "我能看", "我可以看", "我能查", "我可以查",
            "能看到什么", "能查到什么", "可以看什么", "可以查什么",
            "知识库有哪些", "库里有", "文档有哪些", "有哪些文档",
            "有什么文档", "有什么文件", "包含什么", "包含哪些",
            "你知道什么", "你都知道", "你能回答什么",
            "系统里有什么", "库里有什么",
            # 新增：向量库名称相关
            "public_kb", "dept_tech", "dept_hr", "dept_finance", "dept_operation",
            "kb里", "向量库", "有哪些库", "库列表", "kb有哪些"
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
                all_docs = get_engine().collection.get(include=['metadatas'])
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
                restricted_info = get_engine().check_restricted_documents(query, allowed_levels)
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
        """
        构建上下文字符串

        FAQ 优先策略：
        1. FAQ 作为 Golden Context 放在最前面
        2. 普通 Chunk 放在后面
        3. LLM 融合所有上下文生成答案（不阻断）
        """
        # 分离 FAQ 和普通知识库内容
        faq_contexts = [c for c in kb_contexts if c.get('meta', {}).get('chunk_type') == 'faq']
        regular_contexts = [c for c in kb_contexts if c.get('meta', {}).get('chunk_type') != 'faq']

        # FAQ 部分（优先展示）
        faq_parts = []
        for i, c in enumerate(faq_contexts[:3], 1):
            meta = c['meta']
            # FAQ 特殊格式：直接显示问题和答案
            answer = meta.get('faq_answer', c['doc'])
            faq_parts.append(f"[FAQ-{i}] 常见问题\n问题：{c['doc']}\n标准答案：{answer}")

        # 普通知识库部分
        kb_parts = []
        for i, c in enumerate(regular_contexts[:5], 1):
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

        # FAQ 优先排列
        return "\n\n".join(faq_parts + kb_parts + web_parts + graph_parts)

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
            restricted_info = get_engine().check_restricted_documents(query, allowed_levels)

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

        # ==================== Context Compression ====================
        contexts = self._compress_contexts(query, contexts)

        # 生成回答
        if contexts:
            answer = self._generate_fused_answer(query, contexts)
        else:
            # 没有网络搜索结果，直接用 LLM 回答
            answer = self._direct_answer(query, history)

        sources = self._extract_sources(contexts)
        # 只从相关来源提取图片（传入原始查询以提取特定文件名）
        source_names = [s.get("source") for s in sources if s.get("source")]
        rich_media = self._extract_rich_media(contexts, sources_filter=source_names, original_query=query)
        return {
            "answer": answer,
            "sources": sources,
            "web_searched": need_web,
            # 富媒体信息
            "images": rich_media["images"],
            "tables": rich_media["tables"],
            "sections": rich_media["sections"]
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

    # ==================== Context Compression 方法 ====================

    def _compress_contexts(self, query: str, contexts: list) -> list:
        """
        上下文压缩三步走：
        1. Rerank 过滤（score < 0.3 丢弃）
        2. 去重（相似度 > 0.9 只保留一个）
        3. Token 控制

        Args:
            query: 用户问题
            contexts: 检索到的上下文列表

        Returns:
            压缩后的上下文列表
        """
        if not contexts:
            return contexts

        # Step 1: Rerank 过滤（如果有分数信息）
        filtered = self._rerank_filter(contexts)

        # Step 2: 去重
        deduped = self._deduplicate_contexts(filtered)

        # Step 3: Token 控制
        result = self._truncate_to_tokens(deduped, self.MAX_CONTEXT_TOKENS)

        return result

    def _rerank_filter(self, contexts: list) -> list:
        """
        Rerank 过滤 - 保留相关性分数 >= 阈值的上下文

        Args:
            contexts: 上下文列表

        Returns:
            过滤后的上下文列表
        """
        # 如果上下文中有 score 字段，使用阈值过滤
        scored_contexts = [c for c in contexts if c.get('score') is not None]

        if scored_contexts:
            filtered = [c for c in contexts if c.get('score', 0) >= self.RERANK_THRESHOLD]
            # 如果过滤后为空，保留原始列表
            return filtered if filtered else contexts

        # 没有分数信息，保留原始列表
        return contexts

    def _deduplicate_contexts(self, contexts: list, threshold: float = 0.9) -> list:
        """
        去重 - 基于内容相似度去重

        Args:
            contexts: 上下文列表
            threshold: 相似度阈值

        Returns:
            去重后的上下文列表
        """
        if len(contexts) <= 1:
            return contexts

        result = []
        seen_keys = set()

        for c in contexts:
            # 使用文档前 100 字符作为去重 key
            doc = c.get('doc', '')
            key = doc[:100] if doc else ''

            # 同时检查来源是否相同
            meta = c.get('meta', {})
            source = meta.get('source', '')
            page = meta.get('page', '')

            # 组合 key：来源 + 页码 + 内容前缀
            composite_key = f"{source}|{page}|{key}"

            if composite_key not in seen_keys:
                seen_keys.add(composite_key)
                result.append(c)

        return result

    def _truncate_to_tokens(self, contexts: list, max_tokens: int) -> list:
        """
        Token 控制 - 限制上下文总 token 数

        Args:
            contexts: 上下文列表
            max_tokens: 最大 token 数

        Returns:
            截断后的上下文列表
        """
        if not contexts:
            return contexts

        result = []
        total_tokens = 0

        for c in contexts:
            doc = c.get('doc', '')
            # 简单估算：中文约 1.5 字符/token，英文约 4 字符/token
            # 使用保守估算：2 字符/token
            estimated_tokens = len(doc) // 2

            if total_tokens + estimated_tokens <= max_tokens:
                result.append(c)
                total_tokens += estimated_tokens
            else:
                # 达到上限，停止添加
                break

        return result

    def _merge_and_deduplicate(self, old_contexts: list, new_contexts: list) -> list:
        """
        合并去重 - 合并新旧上下文，限制数量

        Args:
            old_contexts: 旧上下文列表
            new_contexts: 新上下文列表

        Returns:
            合并去重后的上下文列表
        """
        all_contexts = old_contexts + new_contexts
        seen_keys = set()
        result = []

        for c in all_contexts:
            doc = c.get('doc', '')
            key = doc[:100] if doc else ''

            if key not in seen_keys:
                seen_keys.add(key)
                result.append(c)

        # 限制最大数量
        return result[:self.MAX_CONTEXT_COUNT]

    # ==================== Answer Grounding 方法 ====================

    def _verify_and_refine_answer(self, query: str, answer: str, contexts: list) -> str:
        """
        答案验证与修正闭环

        Args:
            query: 用户问题
            answer: 生成的答案
            contexts: 上下文列表

        Returns:
            验证后的答案（可能修正）
        """
        # 如果反思器不可用，直接返回原答案
        if not self.reasoning_reflector:
            return answer

        try:
            # 使用现有的反思方法检测幻觉
            reflection = self._reflect_on_answer(query, answer, contexts, verbose=False)

            if not reflection:
                return answer

            # 检查是否有未验证的声明
            unverified_claims = reflection.get('unverified_claims', [])

            if not unverified_claims:
                return answer  # 无幻觉，直接返回

            # 限制：最多重试 1 次
            if self.grounding_retry_count >= self.MAX_GROUNDING_RETRY:
                # 生成不确定回答
                return self._generate_uncertain_answer(query, contexts)

            # 获取新的 context（merge + 去重 + 限制长度）
            verification_queries = reflection.get('verification_queries', [])

            for vq in verification_queries[:2]:  # 最多使用 2 个验证查询
                try:
                    new_results = get_engine().search_knowledge(vq, top_k=3)
                    if new_results and new_results.get('ids') and new_results['ids'][0]:
                        docs = new_results['documents'][0]
                        metas = new_results['metadatas'][0]
                        for doc, meta in zip(docs, metas):
                            contexts.append({
                                'doc': doc,
                                'meta': meta,
                                'source_type': self.SOURCE_KB,
                                'query': vq
                            })
                except Exception:
                    pass

            # 压缩 context
            contexts = self._compress_contexts(query, contexts)

            # 重新生成
            self.grounding_retry_count += 1
            return self._generate_fused_answer(query, contexts)

        except Exception as e:
            return answer  # 出错时返回原答案

    def _generate_uncertain_answer(self, query: str, contexts: list) -> str:
        """
        生成不确定回答 - 当无法验证答案时使用

        Args:
            query: 用户问题
            contexts: 上下文列表

        Returns:
            带不确定性标记的回答
        """
        base_answer = self._generate_fused_answer(query, contexts)
        return f"根据现有信息，{base_answer}\n\n[注：部分信息未能完全验证，请谨慎参考]"

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
        from core.agentic import simple_query

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
    if get_engine().collection.count() == 0:
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
