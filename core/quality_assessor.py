"""
多维质量评估模块

对检索结果进行 4 维质量评估：
1. 相关性（Relevance）：答案是否切题
2. 完整性（Completeness）：信息是否充分
3. 准确性（Accuracy）：是否有冲突信息
4. 覆盖率（Coverage）：多角度覆盖

总阈值：32/40 (80%)

使用方式：
    from core.quality_assessor import QualityAssessor, assess_quality

    assessor = QualityAssessor(llm_client)
    result = assessor.assess(query, documents)

    if result.total_score >= 32:
        # 质量合格，继续生成
        ...
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from config import RAG_CHAT_MODEL


class QualityDimension(Enum):
    """质量评估维度"""
    RELEVANCE = "relevance"         # 相关性：答案是否切题
    COMPLETENESS = "completeness"   # 完整性：信息是否充分
    ACCURACY = "accuracy"           # 准确性：是否有冲突
    COVERAGE = "coverage"           # 覆盖率：多角度覆盖


@dataclass
class DimensionScore:
    """单个维度的评分"""
    dimension: QualityDimension
    score: int              # 0-10 分
    reason: str             # 评分原因
    issues: List[str]       # 发现的问题


@dataclass
class QualityAssessment:
    """质量评估结果"""
    relevance: DimensionScore
    completeness: DimensionScore
    accuracy: DimensionScore
    coverage: DimensionScore
    total_score: int        # 总分（0-40）
    is_sufficient: bool     # 是否达标（>= 32）
    summary: str            # 评估总结
    recommendations: List[str]  # 改进建议


class QualityAssessor:
    """
    多维质量评估器

    基于报告建议的 4 维评估框架，对检索结果进行全面质量检查。
    """

    # 质量阈值（报告建议值）
    QUALITY_THRESHOLD = 32      # 总分阈值（40分制，80%）
    DIMENSION_WEIGHTS = {
        QualityDimension.RELEVANCE: 1.0,
        QualityDimension.COMPLETENESS: 1.0,
        QualityDimension.ACCURACY: 1.0,
        QualityDimension.COVERAGE: 1.0,
    }

    def __init__(self, llm_client=None, model: str = None):
        """
        初始化评估器

        Args:
            llm_client: LLM 客户端（用于语义评估）
            model: 模型名称
        """
        self.llm_client = llm_client
        self.model = model or RAG_CHAT_MODEL

    def assess(self, query: str, documents: List[str],
               metadatas: List[dict] = None) -> QualityAssessment:
        """
        评估检索结果质量

        Args:
            query: 用户查询
            documents: 检索到的文档列表
            metadatas: 文档元数据（可选）

        Returns:
            QualityAssessment: 质量评估结果
        """
        if not documents:
            return self._empty_assessment()

        # 使用 LLM 进行语义评估
        if self.llm_client:
            return self._llm_assess(query, documents, metadatas)
        else:
            # 降级：基于规则的评估
            return self._rule_based_assess(query, documents, metadatas)

    def _llm_assess(self, query: str, documents: List[str],
                    metadatas: List[dict] = None) -> QualityAssessment:
        """
        使用 LLM 进行语义质量评估
        """
        # 构建文档摘要
        doc_summary = self._summarize_documents(documents, metadatas)

        prompt = f"""请对以下检索结果进行多维质量评估。

## 用户查询
{query}

## 检索到的文档摘要
{doc_summary}

## 评估要求
请从 4 个维度进行评分（每个维度 0-10 分）：

1. **相关性（Relevance）**：文档内容是否直接回答用户问题？
   - 10分：完全相关，直接回答
   - 7-9分：高度相关，核心内容匹配
   - 4-6分：部分相关，有侧面信息
   - 0-3分：几乎无关

2. **完整性（Completeness）**：信息是否充分完整？
   - 10分：信息完整，可直接回答
   - 7-9分：基本完整，缺少次要细节
   - 4-6分：部分完整，缺少关键信息
   - 0-3分：信息严重不足

3. **准确性（Accuracy）**：文档之间是否有矛盾冲突？
   - 10分：信息一致，无冲突
   - 7-9分：有轻微表述差异但不影响理解
   - 4-6分：有明显矛盾需要辨别
   - 0-3分：严重冲突，信息不可靠

4. **覆盖率（Coverage）**：是否从多个角度/来源覆盖问题？
   - 10分：多来源、多角度全面覆盖
   - 7-9分：有多个相关来源
   - 4-6分：单一来源但有不同方面
   - 0-3分：覆盖角度单一

请以 JSON 格式返回评估结果：
```json
{{
    "relevance": {{"score": 8, "reason": "原因", "issues": ["问题1"]}},
    "completeness": {{"score": 7, "reason": "原因", "issues": []}},
    "accuracy": {{"score": 9, "reason": "原因", "issues": []}},
    "coverage": {{"score": 6, "reason": "原因", "issues": ["问题1"]}},
    "summary": "整体评估总结",
    "recommendations": ["建议1", "建议2"]
}}
```"""

        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=800
            )

            content = response.choices[0].message.content.strip()
            return self._parse_llm_response(content)

        except Exception as e:
            print(f"[警告] LLM 质量评估失败: {e}")
            return self._rule_based_assess(query, documents, metadatas)

    def _parse_llm_response(self, content: str) -> QualityAssessment:
        """解析 LLM 返回的 JSON"""
        import json
        import re

        # 提取 JSON 块
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = content

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 解析失败，返回默认评估
            return self._default_assessment()

        # 构建维度评分
        relevance = DimensionScore(
            dimension=QualityDimension.RELEVANCE,
            score=min(10, max(0, data.get("relevance", {}).get("score", 5))),
            reason=data.get("relevance", {}).get("reason", ""),
            issues=data.get("relevance", {}).get("issues", [])
        )

        completeness = DimensionScore(
            dimension=QualityDimension.COMPLETENESS,
            score=min(10, max(0, data.get("completeness", {}).get("score", 5))),
            reason=data.get("completeness", {}).get("reason", ""),
            issues=data.get("completeness", {}).get("issues", [])
        )

        accuracy = DimensionScore(
            dimension=QualityDimension.ACCURACY,
            score=min(10, max(0, data.get("accuracy", {}).get("score", 5))),
            reason=data.get("accuracy", {}).get("reason", ""),
            issues=data.get("accuracy", {}).get("issues", [])
        )

        coverage = DimensionScore(
            dimension=QualityDimension.COVERAGE,
            score=min(10, max(0, data.get("coverage", {}).get("score", 5))),
            reason=data.get("coverage", {}).get("reason", ""),
            issues=data.get("coverage", {}).get("issues", [])
        )

        total_score = relevance.score + completeness.score + accuracy.score + coverage.score

        return QualityAssessment(
            relevance=relevance,
            completeness=completeness,
            accuracy=accuracy,
            coverage=coverage,
            total_score=total_score,
            is_sufficient=total_score >= self.QUALITY_THRESHOLD,
            summary=data.get("summary", ""),
            recommendations=data.get("recommendations", [])
        )

    def _rule_based_assess(self, query: str, documents: List[str],
                           metadatas: List[dict] = None) -> QualityAssessment:
        """
        基于规则的质量评估（降级方案）
        """
        # 相关性：基于关键词匹配
        relevance_score = self._assess_relevance(query, documents)

        # 完整性：基于文档长度和数量
        completeness_score = self._assess_completeness(documents)

        # 准确性：假设一致（降级方案无法检测冲突）
        accuracy_score = 8  # 默认较高分数

        # 覆盖率：基于来源多样性
        coverage_score = self._assess_coverage(documents, metadatas)

        total_score = relevance_score + completeness_score + accuracy_score + coverage_score

        return QualityAssessment(
            relevance=DimensionScore(
                dimension=QualityDimension.RELEVANCE,
                score=relevance_score,
                reason=f"关键词匹配评估（规则降级）",
                issues=[]
            ),
            completeness=DimensionScore(
                dimension=QualityDimension.COMPLETENESS,
                score=completeness_score,
                reason=f"基于文档长度和数量评估（规则降级）",
                issues=[]
            ),
            accuracy=DimensionScore(
                dimension=QualityDimension.ACCURACY,
                score=accuracy_score,
                reason="降级方案：假设信息一致",
                issues=[]
            ),
            coverage=DimensionScore(
                dimension=QualityDimension.COVERAGE,
                score=coverage_score,
                reason=f"基于来源多样性评估（规则降级）",
                issues=[]
            ),
            total_score=total_score,
            is_sufficient=total_score >= self.QUALITY_THRESHOLD,
            summary="基于规则的质量评估（LLM 不可用）",
            recommendations=["建议启用 LLM 进行更精确的语义评估"]
        )

    def _assess_relevance(self, query: str, documents: List[str]) -> int:
        """评估相关性（关键词匹配）"""
        try:
            import jieba

            # 提取查询关键词
            query_words = set()
            for word in jieba.cut(query):
                word = word.strip()
                if len(word) >= 2:
                    query_words.add(word.lower())

            if not query_words:
                return 5

            # 计算每个文档的关键词覆盖率
            coverages = []
            for doc in documents:
                doc_lower = doc.lower()
                matched = sum(1 for word in query_words if word in doc_lower)
                coverages.append(matched / len(query_words))

            avg_coverage = sum(coverages) / len(coverages) if coverages else 0

            # 映射到 0-10 分
            if avg_coverage >= 0.8:
                return 9
            elif avg_coverage >= 0.6:
                return 7
            elif avg_coverage >= 0.4:
                return 5
            elif avg_coverage >= 0.2:
                return 3
            else:
                return 1

        except ImportError:
            return 5

    def _assess_completeness(self, documents: List[str]) -> int:
        """评估完整性（基于文档长度和数量）"""
        if not documents:
            return 0

        # 文档数量评估
        doc_count_score = min(3, len(documents))  # 最多 3 分

        # 文档长度评估
        total_length = sum(len(doc) for doc in documents)
        if total_length >= 2000:
            length_score = 7
        elif total_length >= 1000:
            length_score = 5
        elif total_length >= 500:
            length_score = 3
        else:
            length_score = 1

        return min(10, doc_count_score + length_score)

    def _assess_coverage(self, documents: List[str],
                         metadatas: List[dict] = None) -> int:
        """评估覆盖率（来源多样性）"""
        if not metadatas:
            # 无元数据，基于文档内容差异度
            if len(documents) >= 3:
                return 7
            elif len(documents) >= 2:
                return 5
            else:
                return 3

        # 统计来源多样性
        sources = set()
        for meta in metadatas:
            if isinstance(meta, dict):
                source = meta.get("source", "")
                if source:
                    sources.add(source)

        source_count = len(sources)
        if source_count >= 3:
            return 9
        elif source_count >= 2:
            return 7
        elif source_count == 1:
            return 5
        else:
            return 3

    def _summarize_documents(self, documents: List[str],
                            metadatas: List[dict] = None) -> str:
        """生成文档摘要用于 LLM 评估"""
        summary_parts = []

        for i, doc in enumerate(documents[:5], 1):  # 最多 5 个文档
            source = ""
            if metadatas and i <= len(metadatas):
                meta = metadatas[i - 1]
                if isinstance(meta, dict):
                    source = meta.get("source", "未知来源")
                    page = meta.get("page", "")
                    if page:
                        source += f" (第{page}页)"

            content = doc[:300] + "..." if len(doc) > 300 else doc
            summary_parts.append(f"### 文档 {i} ({source})\n{content}")

        return "\n\n".join(summary_parts)

    def _empty_assessment(self) -> QualityAssessment:
        """空评估结果"""
        return QualityAssessment(
            relevance=DimensionScore(
                dimension=QualityDimension.RELEVANCE,
                score=0,
                reason="无检索结果",
                issues=[]
            ),
            completeness=DimensionScore(
                dimension=QualityDimension.COMPLETENESS,
                score=0,
                reason="无检索结果",
                issues=[]
            ),
            accuracy=DimensionScore(
                dimension=QualityDimension.ACCURACY,
                score=0,
                reason="无检索结果",
                issues=[]
            ),
            coverage=DimensionScore(
                dimension=QualityDimension.COVERAGE,
                score=0,
                reason="无检索结果",
                issues=[]
            ),
            total_score=0,
            is_sufficient=False,
            summary="无检索结果可供评估",
            recommendations=["请尝试其他查询方式"]
        )

    def _default_assessment(self) -> QualityAssessment:
        """默认评估结果（解析失败时）"""
        return QualityAssessment(
            relevance=DimensionScore(
                dimension=QualityDimension.RELEVANCE,
                score=5,
                reason="评估解析失败，使用默认分数",
                issues=[]
            ),
            completeness=DimensionScore(
                dimension=QualityDimension.COMPLETENESS,
                score=5,
                reason="评估解析失败，使用默认分数",
                issues=[]
            ),
            accuracy=DimensionScore(
                dimension=QualityDimension.ACCURACY,
                score=5,
                reason="评估解析失败，使用默认分数",
                issues=[]
            ),
            coverage=DimensionScore(
                dimension=QualityDimension.COVERAGE,
                score=5,
                reason="评估解析失败，使用默认分数",
                issues=[]
            ),
            total_score=20,
            is_sufficient=False,
            summary="LLM 评估解析失败",
            recommendations=["请检查 LLM 响应格式"]
        )

    def get_threshold_info(self) -> dict:
        """获取阈值信息"""
        return {
            "quality_threshold": self.QUALITY_THRESHOLD,
            "max_score": 40,
            "pass_percentage": f"{self.QUALITY_THRESHOLD / 40 * 100}%",
            "dimensions": ["relevance", "completeness", "accuracy", "coverage"]
        }


def create_assessor() -> QualityAssessor:
    """
    创建质量评估器实例

    自动从配置获取 LLM 客户端。

    Returns:
        QualityAssessor: 质量评估器实例
    """
    try:
        from openai import OpenAI
        try:
            from config import API_KEY, BASE_URL, RAG_CHAT_MODEL
            MODEL = RAG_CHAT_MODEL
        except ImportError:
            from config import API_KEY, BASE_URL
            MODEL = "qwen3.5-flash"  # fallback

        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        return QualityAssessor(llm_client=client, model=MODEL)

    except Exception as e:
        print(f"[警告] 创建质量评估器失败，使用降级模式: {e}")
        return QualityAssessor()


def assess_quality(query: str, documents: List[str],
                   metadatas: List[dict] = None) -> QualityAssessment:
    """
    便捷函数：评估检索结果质量

    Args:
        query: 用户查询
        documents: 检索到的文档列表
        metadatas: 文档元数据（可选）

    Returns:
        QualityAssessment: 质量评估结果
    """
    assessor = create_assessor()
    return assessor.assess(query, documents, metadatas)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("多维质量评估测试")
    print("=" * 60)

    # 测试用例
    test_cases = [
        {
            "query": "公司报销制度是怎样的？",
            "documents": [
                "公司报销制度规定员工可以报销差旅费用，需提供发票和审批单。报销流程：提交申请 -> 部门审批 -> 财务审核 -> 打款。",
                "差旅报销标准：高铁一等座、飞机经济舱、住宿每天500元内。超过标准需特批。",
                "报销时限：费用发生后30天内提交，逾期不予受理。"
            ],
            "description": "高质量检索结果"
        },
        {
            "query": "量子计算的基本原理",
            "documents": [
                "文档中提到了一些技术细节...",
                "另一个不相关的内容..."
            ],
            "description": "低质量检索结果"
        }
    ]

    assessor = QualityAssessor()  # 不使用 LLM 的规则评估

    print(f"\n阈值配置: {assessor.get_threshold_info()}")
    print()

    for i, case in enumerate(test_cases, 1):
        print(f"测试 {i}: {case['description']}")
        print(f"查询: {case['query']}")
        print(f"文档数: {len(case['documents'])}")

        result = assessor.assess(case['query'], case['documents'])

        print(f"\n评分结果:")
        print(f"  相关性: {result.relevance.score}/10 - {result.relevance.reason}")
        print(f"  完整性: {result.completeness.score}/10 - {result.completeness.reason}")
        print(f"  准确性: {result.accuracy.score}/10 - {result.accuracy.reason}")
        print(f"  覆盖率: {result.coverage.score}/10 - {result.coverage.reason}")
        print(f"\n  总分: {result.total_score}/40")
        print(f"  达标: {'✅ 是' if result.is_sufficient else '❌ 否'} (阈值: 32)")
        print(f"  总结: {result.summary}")
        print()
