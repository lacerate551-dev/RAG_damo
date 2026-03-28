"""
Agentic RAG - 知识库智能问答系统

核心能力：
1. 知识库检索 - 向量检索 + BM25 + Rerank
2. 网络搜索 - 当知识库不足时自动搜索（需配置SERPER_API_KEY）
3. 多源融合 - 智能处理知识库和网络内容
4. Agent决策 - 动态决定检索、改写、分解等操作

使用方式：
    from agentic_rag import AgenticRAG

    rag = AgenticRAG()
    result = rag.process("你的问题")
    print(result["answer"])

配置（可选）：
- 在config.py中添加 SERPER_API_KEY 启用网络搜索
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
    MODEL
)

# 尝试导入搜索API配置
try:
    from config import SERPER_API_KEY
    HAS_SERPER = True
except ImportError:
    HAS_SERPER = False
    SERPER_API_KEY = None


class AgenticRAG:
    """
    Agentic RAG - 知识库智能问答

    支持能力：
    - 知识库检索：向量检索 + BM25 + Rerank
    - 网络搜索：知识库不足时自动搜索
    - 多源融合：智能处理知识库和网络内容
    - Agent决策：动态决定检索、改写、分解等操作
    """

    def __init__(self, max_iterations: int = 3, enable_web_search: bool = True):
        """
        初始化

        Args:
            max_iterations: 最大迭代次数
            enable_web_search: 是否启用网络搜索
        """
        self.max_iterations = max_iterations
        self.enable_web_search = enable_web_search and HAS_SERPER
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

        # 信息来源标记
        self.SOURCE_KB = "知识库"
        self.SOURCE_WEB = "网络搜索"

    def process(self, query: str, verbose: bool = True, history: list = None) -> dict:
        """
        主处理流程

        Args:
            query: 用户问题
            verbose: 是否打印详细过程
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]

        Returns:
            {
                "answer": 回答内容,
                "iterations": 迭代次数,
                "reasoning": 推理过程,
                "contexts": 检索到的上下文,
                "sources": 来源列表
            }
        """
        if verbose:
            print("\n" + "=" * 60)
            print(f"[用户] {query}")
            print("=" * 60)

        # 知识问答流程
        all_contexts = []
        reasoning_trace = []
        current_query = query
        iteration = 0

        if verbose:
            print("\n[开始检索...]")

        while iteration < self.max_iterations:
            iteration += 1

            if verbose:
                print(f"\n--- 第 {iteration} 轮迭代 ---")

            # Agent决策
            decision = self._think(query, current_query, all_contexts, reasoning_trace)

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
                answer = self._generate_fused_answer(query, all_contexts)
                sources = self._extract_sources(all_contexts)
                return {
                    "answer": answer,
                    "iterations": iteration,
                    "reasoning": reasoning_trace,
                    "contexts": all_contexts,
                    "sources": sources
                }

            elif decision["action"] == "kb_search":
                # 知识库检索
                if verbose:
                    print(f"[知识库检索] {current_query}")

                results = search_knowledge(current_query, top_k=5)
                docs = results.get('documents', [[]])[0]
                metas = results.get('metadatas', [[]])[0]

                for doc, meta in zip(docs, metas):
                    all_contexts.append({
                        'doc': doc,
                        'meta': meta,
                        'source_type': self.SOURCE_KB,
                        'query': current_query
                    })

                if verbose:
                    print(f"   找到 {len(docs)} 个片段")

            elif decision["action"] == "web_search":
                # 网络搜索
                if not self.enable_web_search:
                    if verbose:
                        print("[警告] 网络搜索未配置，跳过")
                    continue

                search_query = decision.get('search_query', current_query)
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

                if verbose:
                    print(f"   找到 {len(web_results)} 条结果")

            elif decision["action"] == "rewrite":
                current_query = decision.get("new_query", current_query)
                if verbose:
                    print(f"[改写查询] {current_query}")

            elif decision["action"] == "decompose":
                sub_queries = decision.get("sub_queries", [])
                if verbose:
                    print(f"[分解问题] {len(sub_queries)} 个子问题")

                for sub_q in sub_queries:
                    results = search_knowledge(sub_q, top_k=3)
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
        answer = self._generate_fused_answer(query, all_contexts)
        sources = self._extract_sources(all_contexts)
        return {
            "answer": answer,
            "iterations": iteration,
            "reasoning": reasoning_trace,
            "contexts": all_contexts,
            "sources": sources
        }

    def _extract_sources(self, contexts: list) -> list:
        """提取来源列表"""
        sources = []
        for c in contexts:
            meta = c.get('meta', {})
            source_type = c.get('source_type', '未知')

            if source_type == self.SOURCE_KB:
                source_str = meta.get('source', '未知')
                if 'page' in meta:
                    source_str += f" 第{meta['page']}页"
            else:
                source_str = meta.get('title', meta.get('source', '未知'))

            sources.append({
                "source": source_str,
                "type": source_type,
                "snippet": c.get('doc', '')[:100] + "..." if len(c.get('doc', '')) > 100 else c.get('doc', '')
            })
        return sources

    def _think(self, original_query: str, current_query: str,
               contexts: list, history: list) -> dict:
        """
        Agent决策

        决策类型：
        - kb_search: 检索知识库
        - web_search: 网络搜索
        - answer: 生成答案
        - rewrite: 改写查询
        - decompose: 分解问题
        """
        # 分析现有信息
        kb_count = sum(1 for c in contexts if c.get('source_type') == self.SOURCE_KB)
        web_count = sum(1 for c in contexts if c.get('source_type') == self.SOURCE_WEB)

        # 构建上下文摘要
        context_summary = ""
        if contexts:
            kb_docs = [c['doc'][:200] for c in contexts if c.get('source_type') == self.SOURCE_KB][:2]
            web_docs = [c['doc'][:200] for c in contexts if c.get('source_type') == self.SOURCE_WEB][:2]

            if kb_docs:
                context_summary += f"\n[知识库内容({kb_count}条)]\n" + "\n".join(f"- {d}..." for d in kb_docs)
            if web_docs:
                context_summary += f"\n[网络内容({web_count}条)]\n" + "\n".join(f"- {d}..." for d in web_docs)

        prompt = f"""你是一个智能信息检索助手。请分析问题并决定下一步行动。

【用户原始问题】
{original_query}

【当前查询】
{current_query}

【已有信息】
{context_summary if context_summary else "暂无"}

【迭代历史】
已进行 {len(history)} 轮，已检索知识库 {kb_count} 条，网络 {web_count} 条

【决策选项】

1. **kb_search** - 检索知识库
   - 适用：首次检索、知识库可能有所需信息
   - 输出: {{"action": "kb_search"}}

2. **web_search** - 网络搜索
   - 适用：知识库信息不足、需要最新信息、需要更权威的来源
   - 输出: {{"action": "web_search", "search_query": "搜索词", "reason": "为什么需要网络搜索"}}

3. **answer** - 生成答案
   - 适用：信息足够回答问题
   - 输出: {{"action": "answer", "reason": "信息已足够"}}

4. **rewrite** - 改写查询
   - 适用：查询词不准确、检索结果差
   - 输出: {{"action": "rewrite", "new_query": "改写后的查询", "reason": "为什么改写"}}

5. **decompose** - 分解问题
   - 适用：问题包含多个子问题
   - 输出: {{"action": "decompose", "sub_queries": ["子问题1", "子问题2"], "reason": "为什么分解"}}

【决策原则】
- 首轮优先检索知识库（kb_search）
- 如果知识库信息明显过时或不完整，考虑 web_search
- 网络搜索的查询词应简洁、专业
- 避免重复检索相同内容
- 信息足够时立即 answer，不要浪费轮次

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

            valid_actions = ["answer", "kb_search", "web_search", "rewrite", "decompose"]
            if decision.get("action") not in valid_actions:
                decision = {"action": "kb_search", "reason": "默认检索知识库"}

            return decision

        except Exception as e:
            return {"action": "kb_search", "reason": f"决策解析失败: {str(e)}"}

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

    def _generate_fused_answer(self, query: str, contexts: list) -> str:
        """
        生成融合答案 - 智能处理多源信息

        处理策略：
        1. 区分知识库和网络来源
        2. 检测内容冲突
        3. 判断时效性
        4. 智能融合
        """
        # 分离不同来源
        kb_contexts = [c for c in contexts if c.get('source_type') == self.SOURCE_KB]
        web_contexts = [c for c in contexts if c.get('source_type') == self.SOURCE_WEB]

        # 构建来源信息
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

        context_str = "\n\n".join(kb_parts + web_parts)

        # 使用增强的提示词
        prompt = f"""你是一个严谨的智能助手，需要综合多个信息来源回答问题。

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

4. **来源标注**
   - 每个关键信息必须标注来源
   - 格式：[知识库-文件名-页码] 或 [网络-标题]

【回答格式】

### 核心答案
（直接回答问题，整合最可靠的信息）

### 详细说明
（分点展开，每个信息点标注来源）

### 来源汇总
- 知识库：共{len(kb_contexts)}条
- 网络搜索：共{len(web_contexts)}条

请回答："""

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

    def _format_source(self, meta: dict, source_type: str) -> str:
        """格式化来源信息"""
        if source_type == self.SOURCE_WEB:
            return f"{meta.get('title', '网络')} ({meta.get('source', '')})"
        else:
            source_parts = [meta.get('source', '未知文件')]
            if 'page' in meta:
                source_parts.append(f"第{meta['page']}页")
            return " ".join(source_parts)

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
