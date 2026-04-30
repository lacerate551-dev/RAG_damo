"""
意图分析器 - 改写 + 双层判断

核心功能：
1. 问题改写：指代消解、省略补全
2. 双层判断：
   - 历史是否可答
   - 是否需要外部知识
3. 输出：决策（use_context / need_retrieval）
4. 语义缓存：相似问题复用结果

设计原则：
- 使用轻量 LLM 完成改写和判断
- 替代硬编码规则，更灵活可维护
- 语义缓存减少 LLM 调用
"""

import json
import logging
import hashlib
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class IntentAnalysis:
    """意图分析结果"""
    rewritten_query: str           # 改写后的完整问题
    use_context: bool              # 是否使用上下文回答
    need_retrieval: bool           # 是否需要检索
    confidence: float              # 置信度
    reason: str                    # 判断理由
    context_images: List[dict]     # 上下文中的图片信息

    def to_dict(self) -> dict:
        """转换为字典（用于缓存）"""
        return {
            "rewritten_query": self.rewritten_query,
            "use_context": self.use_context,
            "need_retrieval": self.need_retrieval,
            "confidence": self.confidence,
            "reason": self.reason,
            "context_images": self.context_images
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IntentAnalysis":
        """从字典创建（用于缓存读取）"""
        return cls(
            rewritten_query=data.get("rewritten_query", ""),
            use_context=data.get("use_context", False),
            need_retrieval=data.get("need_retrieval", True),
            confidence=data.get("confidence", 0.5),
            reason=data.get("reason", ""),
            context_images=data.get("context_images", [])
        )


class IntentAnalyzer:
    """
    意图分析器

    使用 LLM 一次调用完成：
    1. 问题改写（指代消解）
    2. 意图判断（是否需要检索）
    """

    SYSTEM_PROMPT = """你是一个意图分析助手。你的任务是分析用户问题，判断它需要什么类型的回答。

## 任务说明

根据对话历史和当前用户消息，输出一个 JSON 对象，包含以下字段：

1. **rewritten_query**: 改写后的完整问题
   - 如果问题包含指代（如"这两张图片"、"继续说"），将其改写为完整、独立的问题
   - 例如："分析一下这两张图片" → "分析一下对话历史中提到的图片"
   - 如果问题本身已经完整，直接返回原文

2. **use_context**: 布尔值
   - true: 问题依赖历史对话中的信息，答案已经在历史回答中
   - false: 问题是新问题，需要新的回答

3. **need_retrieval**: 布尔值
   - true: 需要从知识库检索信息才能回答
   - false: 可以直接使用历史上下文或自己的知识回答

4. **reason**: 简短说明判断理由

## 判断原则

### use_context = true 的情况：
- 用户引用了历史对话中的内容（"这两张图片"、"上面的数据"、"继续说"）
- 问题是对历史回答的追问或深入询问
- 答案可以从历史回答中直接得出

### need_retrieval = true 的情况：
- 问题询问新的事实、数据、流程
- 问题提到了具体的图号、表号、章节
- 问题需要知识库中的文档来回答
- 用户明确要求查看知识库内容
- **重要：用户重复提问相同问题**（这可能意味着之前的回答不满意或不正确）

### 两者都可以为 false：
- 简单的闲聊、问候
- 基于附件/图片的视觉分析请求（图片信息在上下文中）
- 常识性问题

## 重要规则

**当用户重复提问相同或相似问题时，必须设置 need_retrieval = true！**

原因：
1. 用户可能对之前的回答不满意
2. 之前的回答可能包含错误信息
3. 需要重新检索以确保回答准确性

判断重复提问的方法：
- 当前问题与历史中的用户问题语义相同或高度相似
- 例如：用户之前问"发电量"，现在又问"发电量统计"
- 例如：用户之前问过某问题，现在换个方式再问

## 输出格式

只输出一个 JSON 对象，不要其他内容：
```json
{
    "rewritten_query": "改写后的问题",
    "use_context": true/false,
    "need_retrieval": true/false,
    "reason": "判断理由"
}
```"""

    def __init__(self, model: str = None, use_cache: bool = True):
        """
        初始化意图分析器

        Args:
            model: 使用的 LLM 模型（默认从配置读取）
            use_cache: 是否启用语义缓存
        """
        self.model = model
        self.use_cache = use_cache
        self._client = None
        self._cache = None
        self._embedding_model = None

    def _get_client(self):
        """获取 LLM 客户端"""
        if self._client is None:
            from config import get_llm_client
            self._client = get_llm_client()
        return self._client

    def _get_cache(self):
        """获取语义缓存"""
        if self._cache is None and self.use_cache:
            try:
                from core.semantic_cache import get_semantic_cache
                self._cache = get_semantic_cache()
            except Exception as e:
                logger.warning(f"语义缓存初始化失败: {e}")
                self._cache = None
        return self._cache

    def _get_embedding(self, text: str):
        """获取文本向量，优先复用 engine 已加载的模型"""
        if self._embedding_model is None:
            # 优先从 engine 复用已加载的 embedding 模型
            try:
                from core.engine import get_engine
                self._embedding_model = get_engine().embedding_model
                logger.debug("复用 engine 的 embedding 模型")
            except Exception as e:
                # fallback: 单独加载
                logger.warning(f"无法获取 engine 的 embedding 模型: {e}，尝试单独加载")
                try:
                    from sentence_transformers import SentenceTransformer
                    self._embedding_model = SentenceTransformer('models/bge-base-zh-v1.5')
                except Exception as e2:
                    logger.warning(f"嵌入模型初始化失败: {e2}")
                    return None

        try:
            import numpy as np
            emb = self._embedding_model.encode(text)
            return np.array(emb, dtype='float32')
        except Exception as e:
            logger.warning(f"向量化失败: {e}")
            return None

    def analyze(
        self,
        query: str,
        history: List[dict],
        context_images: List[dict] = None
    ) -> IntentAnalysis:
        """
        分析用户意图

        Args:
            query: 用户当前问题
            history: 对话历史 [{"role": "user/assistant", "content": "...", "metadata": {...}}]
            context_images: 上下文中的图片信息

        Returns:
            IntentAnalysis: 分析结果
        """
        # 构建历史摘要
        history_summary = self._build_history_summary(history, context_images)

        # 尝试从缓存获取
        cache = self._get_cache()
        if cache:
            # 使用 query + 历史关键信息作为缓存键
            cache_key = self._build_cache_key(query, history)
            cache_emb = self._get_embedding(cache_key)

            if cache_emb is not None:
                cached = cache.get(cache_emb)
                if cached:
                    logger.info(f"意图分析缓存命中: {cached.get('reason', '')[:50]}")
                    return IntentAnalysis.from_dict(cached)

        # 构建 prompt
        user_prompt = f"""## 对话历史

{history_summary}

## 当前用户消息

{query}

请分析用户的意图，输出 JSON 对象。"""

        try:
            client = self._get_client()
            model = self.model or self._get_default_model()

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=300
            )

            content = response.choices[0].message.content.strip()

            # 解析 JSON
            result = self._parse_json(content)

            if result:
                analysis = IntentAnalysis(
                    rewritten_query=result.get("rewritten_query", query),
                    use_context=result.get("use_context", False),
                    need_retrieval=result.get("need_retrieval", True),
                    confidence=0.9,
                    reason=result.get("reason", ""),
                    context_images=context_images or []
                )

                # 存入缓存
                if cache and cache_emb is not None:
                    cache.set(cache_emb, analysis.to_dict())

                return analysis

        except Exception as e:
            logger.warning(f"意图分析失败: {e}，使用默认值")

        # 默认值：需要检索
        return IntentAnalysis(
            rewritten_query=query,
            use_context=False,
            need_retrieval=True,
            confidence=0.5,
            reason="意图分析失败，默认走检索流程",
            context_images=context_images or []
        )

    def _build_cache_key(self, query: str, history: List[dict]) -> str:
        """
        构建缓存键

        结合 query 和历史关键信息，确保相同上下文下的相同问题能命中缓存
        """
        parts = [query]

        # 添加最近历史的关键信息
        if history:
            for msg in history[-2:]:  # 最近1轮
                role = msg.get("role", "")
                content = msg.get("content", "")[:100]  # 截断
                parts.append(f"{role[:1]}:{content}")

        return " | ".join(parts)

    def _build_history_summary(
        self,
        history: List[dict],
        context_images: List[dict] = None
    ) -> str:
        """
        构建历史摘要

        Args:
            history: 对话历史
            context_images: 上下文中的图片

        Returns:
            历史摘要文本
        """
        if not history:
            return "（无历史对话）"

        parts = []

        # 提取最近 3 轮对话
        recent_history = history[-6:]  # 最多 3 轮（每轮 2 条消息）

        for msg in recent_history:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")

            # 截断过长的内容
            if len(content) > 500:
                content = content[:500] + "..."

            parts.append(f"【{role}】{content}")

            # 提取图片信息
            metadata = msg.get("metadata", {})
            if isinstance(metadata, dict):
                images = metadata.get("images", [])
                if images:
                    for img in images[:3]:
                        if isinstance(img, dict):
                            desc = img.get("description", "")[:100]
                            img_type = img.get("type", "图片")
                            parts.append(f"  └─ {img_type}: {desc}")

        # 添加图片上下文
        if context_images:
            parts.append("\n【上下文中的图片】")
            for img in context_images[:5]:
                desc = img.get("description", "")[:100]
                img_type = img.get("type", "图片")
                parts.append(f"  - {img_type}: {desc}")

        return "\n".join(parts)

    def _parse_json(self, content: str) -> Optional[dict]:
        """解析 JSON 响应"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except:
            pass

        # 尝试提取 JSON 块
        import re
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass

        return None

    def _get_default_model(self) -> str:
        """获取默认模型"""
        try:
            from config import DASHSCOPE_MODEL
            return DASHSCOPE_MODEL
        except:
            return "qwen-plus"


# ==================== 便捷函数 ====================

_analyzer = None

def get_intent_analyzer() -> IntentAnalyzer:
    """获取意图分析器单例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = IntentAnalyzer()
    return _analyzer


def analyze_intent(
    query: str,
    history: List[dict],
    context_images: List[dict] = None
) -> IntentAnalysis:
    """
    便捷函数：分析用户意图

    Args:
        query: 用户问题
        history: 对话历史
        context_images: 上下文中的图片

    Returns:
        IntentAnalysis: 分析结果
    """
    analyzer = get_intent_analyzer()
    return analyzer.analyze(query, history, context_images)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    # 测试用例
    test_cases = [
        {
            "query": "分析一下这两张图片",
            "history": [
                {"role": "user", "content": "三峡工程有什么图片"},
                {"role": "assistant", "content": "我找到了三峡大坝的示意图...", "metadata": {"images": [{"type": "示意图", "description": "三峡大坝全景"}]}},
            ],
            "expected": {"use_context": True, "need_retrieval": False}
        },
        {
            "query": "三峡水库补水调度统计",
            "history": [],
            "expected": {"use_context": False, "need_retrieval": True}
        },
        {
            "query": "继续说",
            "history": [
                {"role": "user", "content": "介绍一下三峡工程"},
                {"role": "assistant", "content": "三峡工程是..."},
            ],
            "expected": {"use_context": True, "need_retrieval": False}
        },
    ]

    print("=" * 60)
    print("意图分析器测试")
    print("=" * 60)

    analyzer = IntentAnalyzer()

    for i, case in enumerate(test_cases, 1):
        print(f"\n--- 测试 {i} ---")
        print(f"问题: {case['query']}")

        result = analyzer.analyze(case["query"], case["history"])

        print(f"改写后: {result.rewritten_query}")
        print(f"use_context: {result.use_context}")
        print(f"need_retrieval: {result.need_retrieval}")
        print(f"理由: {result.reason}")
