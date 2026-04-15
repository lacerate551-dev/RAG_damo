"""
推理反思模块（Re²Search）

在答案生成过程中，自动识别未经验证的声明，触发补充检索进行验证。

核心机制：
1. 从生成的答案中提取关键声明（claims）
2. 识别哪些声明缺乏检索证据支持
3. 对未验证声明触发补充检索
4. 根据补充信息修正或增强答案

使用方式：
    from core.reasoning_reflector import ReasoningReflector, reflect_and_verify

    reflector = ReasoningReflector(llm_client)
    result = reflector.reflect(query, answer, contexts)

    if result.has_unverified_claims:
        # 触发补充检索
        ...
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum


class ClaimType(Enum):
    """声明类型"""
    FACTUAL = "factual"         # 事实性声明（可验证）
    OPINION = "opinion"         # 观点性声明（主观）
    INFERENCE = "inference"     # 推论性声明（逻辑推导）
    HEDGED = "hedged"          # 保留性声明（可能、也许）


@dataclass
class Claim:
    """单个声明"""
    content: str               # 声明内容
    claim_type: ClaimType      # 声明类型
    is_verified: bool          # 是否已验证
    supporting_contexts: List[str]  # 支持该声明的上下文
    confidence: float          # 置信度（0-1）


@dataclass
class ReflectionResult:
    """反思结果"""
    original_answer: str       # 原始答案
    claims: List[Claim]        # 提取的声明列表
    unverified_claims: List[Claim]  # 未验证的声明
    has_unverified_claims: bool    # 是否存在未验证声明
    verification_queries: List[str]  # 建议的验证查询
    reflection_summary: str    # 反思总结
    should_supplement: bool    # 是否需要补充检索


class ReasoningReflector:
    """
    推理反思器

    在答案生成后，分析答案中的声明，识别未经验证的部分，
    触发补充检索以提高答案质量。
    """

    # 需要关注的关键词（可能表示未验证声明）
    UNVERIFIED_MARKERS = [
        "可能", "也许", "大概", "应该", "估计",
        "通常", "一般", "往往", "多半",
        "我认为", "我猜测", "似乎", "看起来"
    ]

    # 事实性声明关键词
    FACTUAL_MARKERS = [
        "是", "有", "包括", "规定", "要求", "标准",
        "流程", "步骤", "时间", "金额", "数量"
    ]

    def __init__(self, llm_client=None, model: str = None):
        """
        初始化反思器

        Args:
            llm_client: LLM 客户端
            model: 模型名称
        """
        self.llm_client = llm_client
        self.model = model or "qwen3.5-flash"

    def reflect(self, query: str, answer: str,
                contexts: List[str] = None) -> ReflectionResult:
        """
        对答案进行推理反思

        Args:
            query: 用户查询
            answer: 生成的答案
            contexts: 检索上下文

        Returns:
            ReflectionResult: 反思结果
        """
        if not answer:
            return self._empty_reflection()

        # 使用 LLM 进行声明提取和验证
        if self.llm_client:
            return self._llm_reflect(query, answer, contexts)
        else:
            # 降级：基于规则的反思
            return self._rule_based_reflect(query, answer, contexts)

    def _llm_reflect(self, query: str, answer: str,
                     contexts: List[str] = None) -> ReflectionResult:
        """
        使用 LLM 进行深度反思
        """
        # 构建上下文摘要
        context_summary = ""
        if contexts:
            context_summary = "\n\n".join([
                f"[上下文 {i+1}] {ctx[:300]}..."
                for i, ctx in enumerate(contexts[:5])
            ])

        prompt = f"""请对以下答案进行推理反思分析。

## 用户问题
{query}

## 生成的答案
{answer}

## 检索到的上下文
{context_summary if context_summary else "（无检索上下文）"}

## 分析要求
1. 从答案中提取关键声明（claims）
2. 判断每个声明是否有上下文支持
3. 识别未验证的声明
4. 生成验证查询建议

请以 JSON 格式返回：
```json
{{
    "claims": [
        {{
            "content": "声明内容",
            "type": "factual/opinion/inference/hedged",
            "verified": true/false,
            "supporting_evidence": "支持证据或'无'",
            "confidence": 0.8
        }}
    ],
    "unverified_claims_count": 2,
    "verification_queries": ["建议的验证查询1", "建议的验证查询2"],
    "summary": "反思总结",
    "should_supplement": true/false
}}
```"""

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1000
            )

            content = response.choices[0].message.content.strip()
            return self._parse_llm_response(answer, content)

        except Exception as e:
            print(f"[警告] LLM 反思失败: {e}")
            return self._rule_based_reflect(query, answer, contexts)

    def _parse_llm_response(self, original_answer: str,
                            content: str) -> ReflectionResult:
        """解析 LLM 返回的 JSON"""
        import json
        import re

        # 提取 JSON 块
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = content

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return self._default_reflection(original_answer)

        # 解析声明
        claims = []
        unverified_claims = []

        for claim_data in data.get("claims", []):
            claim_type_str = claim_data.get("type", "factual")
            claim_type = {
                "factual": ClaimType.FACTUAL,
                "opinion": ClaimType.OPINION,
                "inference": ClaimType.INFERENCE,
                "hedged": ClaimType.HEDGED
            }.get(claim_type_str, ClaimType.FACTUAL)

            claim = Claim(
                content=claim_data.get("content", ""),
                claim_type=claim_type,
                is_verified=claim_data.get("verified", False),
                supporting_contexts=[claim_data.get("supporting_evidence", "")],
                confidence=claim_data.get("confidence", 0.5)
            )
            claims.append(claim)

            if not claim.is_verified:
                unverified_claims.append(claim)

        return ReflectionResult(
            original_answer=original_answer,
            claims=claims,
            unverified_claims=unverified_claims,
            has_unverified_claims=len(unverified_claims) > 0,
            verification_queries=data.get("verification_queries", []),
            reflection_summary=data.get("summary", ""),
            should_supplement=data.get("should_supplement", False)
        )

    def _rule_based_reflect(self, query: str, answer: str,
                            contexts: List[str] = None) -> ReflectionResult:
        """
        基于规则的反思（降级方案）
        """
        claims = []
        unverified_claims = []
        verification_queries = []

        # 简单句子分割
        sentences = self._split_sentences(answer)

        for sentence in sentences:
            if len(sentence.strip()) < 10:
                continue

            # 检测声明类型
            claim_type = self._detect_claim_type(sentence)

            # 检测是否已验证
            is_verified = self._check_verification(sentence, contexts)
            confidence = self._estimate_confidence(sentence, is_verified)

            claim = Claim(
                content=sentence.strip(),
                claim_type=claim_type,
                is_verified=is_verified,
                supporting_contexts=[],
                confidence=confidence
            )
            claims.append(claim)

            if not is_verified and claim_type in [ClaimType.FACTUAL, ClaimType.INFERENCE]:
                unverified_claims.append(claim)
                # 生成验证查询
                verification_queries.append(f"验证：{sentence.strip()[:50]}")

        has_unverified = len(unverified_claims) > 0
        should_supplement = has_unverified and len(unverified_claims) <= 3

        summary = f"共提取 {len(claims)} 个声明，其中 {len(unverified_claims)} 个未验证"
        if has_unverified:
            summary += "，建议补充检索验证"

        return ReflectionResult(
            original_answer=answer,
            claims=claims,
            unverified_claims=unverified_claims,
            has_unverified_claims=has_unverified,
            verification_queries=verification_queries[:3],
            reflection_summary=summary,
            should_supplement=should_supplement
        )

    def _split_sentences(self, text: str) -> List[str]:
        """分割句子"""
        import re
        # 按中英文标点分割
        sentences = re.split(r'[。！？\.\!\?]\s*', text)
        return [s.strip() for s in sentences if s.strip()]

    def _detect_claim_type(self, sentence: str) -> ClaimType:
        """检测声明类型"""
        # 保留性声明
        if any(marker in sentence for marker in self.UNVERIFIED_MARKERS):
            return ClaimType.HEDGED

        # 事实性声明
        if any(marker in sentence for marker in self.FACTUAL_MARKERS):
            return ClaimType.FACTUAL

        # 默认为推论
        return ClaimType.INFERENCE

    def _check_verification(self, sentence: str,
                           contexts: List[str] = None) -> bool:
        """检查声明是否已验证"""
        if not contexts:
            return False

        # 简单关键词匹配
        keywords = self._extract_keywords(sentence)
        if not keywords:
            return False

        for ctx in contexts:
            matches = sum(1 for kw in keywords if kw in ctx)
            if matches >= len(keywords) * 0.5:
                return True

        return False

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        try:
            import jieba
            keywords = []
            for word in jieba.cut(text):
                word = word.strip()
                if len(word) >= 2 and word.isalpha():
                    keywords.append(word)
            return list(set(keywords))[:10]
        except ImportError:
            return []

    def _estimate_confidence(self, sentence: str, is_verified: bool) -> float:
        """估计置信度"""
        base_confidence = 0.8 if is_verified else 0.4

        # 保留性声明降低置信度
        if any(marker in sentence for marker in self.UNVERIFIED_MARKERS):
            base_confidence -= 0.2

        return max(0.1, min(1.0, base_confidence))

    def _empty_reflection(self) -> ReflectionResult:
        """空反思结果"""
        return ReflectionResult(
            original_answer="",
            claims=[],
            unverified_claims=[],
            has_unverified_claims=False,
            verification_queries=[],
            reflection_summary="无答案可供反思",
            should_supplement=False
        )

    def _default_reflection(self, answer: str) -> ReflectionResult:
        """默认反思结果（解析失败时）"""
        return ReflectionResult(
            original_answer=answer,
            claims=[],
            unverified_claims=[],
            has_unverified_claims=False,
            verification_queries=[],
            reflection_summary="反思解析失败",
            should_supplement=False
        )

    def get_info(self) -> dict:
        """获取反思器信息"""
        return {
            "model": self.model,
            "has_llm": self.llm_client is not None,
            "unverified_markers_count": len(self.UNVERIFIED_MARKERS),
            "factual_markers_count": len(self.FACTUAL_MARKERS)
        }


def create_reflector() -> ReasoningReflector:
    """
    创建反思器实例

    Returns:
        ReasoningReflector: 反思器实例
    """
    try:
        from openai import OpenAI
        try:
            from config import API_KEY, BASE_URL, MODEL
        except ImportError:
            from config import API_KEY, BASE_URL
            MODEL = "qwen3.5-flash"

        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        return ReasoningReflector(llm_client=client, model=MODEL)

    except Exception as e:
        print(f"[警告] 创建反思器失败，使用降级模式: {e}")
        return ReasoningReflector()


def reflect_and_verify(query: str, answer: str,
                       contexts: List[str] = None) -> ReflectionResult:
    """
    便捷函数：反思并验证答案

    Args:
        query: 用户查询
        answer: 生成的答案
        contexts: 检索上下文

    Returns:
        ReflectionResult: 反思结果
    """
    reflector = create_reflector()
    return reflector.reflect(query, answer, contexts)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("推理反思测试")
    print("=" * 60)

    # 测试用例
    test_query = "公司的报销制度是怎样的？"
    test_answer = """
根据公司规定，员工可以报销差旅费用。

报销流程通常包括：提交申请、部门审批、财务审核、打款。

可能需要提供发票和审批单，大概在30天内完成。

我认为公司对报销标准有明确要求，但具体金额我不太确定。
"""
    test_contexts = [
        "公司报销制度规定员工可以报销差旅费用，需提供发票和审批单。",
        "报销流程：提交申请 -> 部门审批 -> 财务审核 -> 打款。"
    ]

    reflector = ReasoningReflector()  # 不使用 LLM 的规则反思

    print(f"\n反思器信息: {reflector.get_info()}")
    print()

    result = reflector.reflect(test_query, test_answer, test_contexts)

    print(f"反思总结: {result.reflection_summary}")
    print(f"需要补充检索: {'是' if result.should_supplement else '否'}")
    print(f"\n声明分析:")
    for i, claim in enumerate(result.claims, 1):
        status = "✅ 已验证" if claim.is_verified else "⚠️ 未验证"
        print(f"  {i}. [{claim.claim_type.value}] {status}")
        print(f"     内容: {claim.content[:50]}...")
        print(f"     置信度: {claim.confidence:.2f}")

    if result.verification_queries:
        print(f"\n建议验证查询:")
        for q in result.verification_queries:
            print(f"  - {q}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)
