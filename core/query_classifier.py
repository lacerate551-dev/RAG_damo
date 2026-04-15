"""
查询分类器 - 分层查询分类与检索配置生成

核心功能：
1. 规则快速分类（无 LLM 调用）
2. 查询类型识别
3. 关键词提取
4. 检索配置生成

使用方式：
    from core.query_classifier import QueryClassifier, QueryType

    classifier = QueryClassifier()
    result = classifier.classify("出差报销标准是多少？")
    print(result.query_type)  # QueryType.FACT
    print(result.search_config)  # {"top_k": 5, ...}
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
import re


class QueryType(Enum):
    """查询类型枚举"""
    META = "meta"              # 元问题：文件列表、权限等
    REALTIME = "realtime"      # 实时信息：天气、新闻
    SIMPLE = "simple"          # 简单查询：单实体、单属性（短查询）
    FACT = "fact"              # 事实查询：单一答案
    COMPARISON = "comparison"  # 比较分析：差异、对比
    PROCESS = "process"        # 流程指引：步骤、流程
    FILE_SPECIFIC = "file_specific"  # 特定文件内查询（如 "xxx.pdf中有哪些图片"）


@dataclass
class ClassifiedQuery:
    """分类后的查询结果"""
    query_type: QueryType
    original_query: str
    processed_query: str       # 处理后的查询（如实体补全）
    keywords: List[str]        # 提取的关键词
    entities: List[str]        # 识别的实体
    confidence: float          # 分类置信度
    skip_llm_decision: bool    # 是否跳过 LLM 决策
    search_config: Dict[str, Any]  # 检索配置
    source_filter: Optional[str] = None  # 文件名过滤（FILE_SPECIFIC 类型时使用）

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "query_type": self.query_type.value,
            "original_query": self.original_query,
            "processed_query": self.processed_query,
            "keywords": self.keywords,
            "entities": self.entities,
            "confidence": self.confidence,
            "skip_llm_decision": self.skip_llm_decision,
            "search_config": self.search_config,
            "source_filter": self.source_filter
        }


class QueryClassifier:
    """
    分层查询分类器

    分层架构：
    1. 第一层：规则快速分类（元问题、实时信息）
    2. 第二层：查询类型分类（事实、比较、流程）
    3. 输出：检索配置

    设计原则：
    - 规则基于用户表达习惯，与具体文件内容无关
    - 支持后续扩展公司特有术语
    """

    # ==================== 规则关键词 ====================
    # 元问题模式：关于知识库本身的问题
    META_PATTERNS = [
        "有哪些文件", "什么文件", "哪些文件", "文件列表", "文件目录",
        "能查看", "可以查看", "有权限查看", "权限查看",
        "能访问", "可以访问", "有权限访问",
        "知识库有哪些", "库里有", "文档有哪些", "有哪些文档",
        "有什么文档", "有什么文件", "包含什么", "包含哪些",
        "你知道什么", "你都知道", "你能回答什么",
        "系统里有什么", "库里有什么", "能做什么", "可以帮助",
        # 新增：向量库名称相关
        "public_kb", "dept_tech", "dept_hr", "dept_finance", "dept_operation",
        "kb里", "向量库", "有哪些库", "库列表", "kb有哪些"
    ]

    # 实时信息模式：需要网络搜索的问题
    REALTIME_PATTERNS = [
        "今天", "昨天", "最新", "最近", "当前",
        "天气", "新闻", "股价", "汇率", "实时",
        "现在", "本周", "本月", "今年",
        "发生了", "热点", "动态"
    ]

    # 比较分析模式：需要多源对比
    COMPARISON_PATTERNS = [
        "区别", "对比", "差异", "比较", "不同",
        "哪个更好", "哪个更", "vs", "还是",
        "一样吗", "有什么不同", "有什么区别",
        "优缺点", "利弊", "优劣"
    ]

    # 流程指引模式：需要步骤说明
    PROCESS_PATTERNS = [
        "流程", "步骤", "怎么办理", "如何申请",
        "操作流程", "办理流程", "申请流程",
        "怎么做", "怎样", "操作步骤",
        "审批流程", "审批步骤", "办理手续"
    ]

    # 业务关键词（用于判断查询是否有明确主语）
    BUSINESS_KEYWORDS = [
        "报销", "出差", "请假", "工资", "合同", "审批",
        "招聘", "培训", "考核", "绩效", "调岗", "离职",
        "入职", "试用期", "加班", "考勤", "年假", "病假",
        "婚假", "产假", "陪产假", "补助", "补贴", "奖金"
    ]

    # 停用词
    STOP_WORDS = {
        "的", "是", "有", "在", "和", "了", "吗", "呢", "啊",
        "什么", "怎么", "如何", "哪", "谁", "哪位", "多少",
        "这个", "那个", "这些", "那些", "我", "你", "他",
        "可以", "能够", "需要", "应该", "会", "能", "要"
    }

    # 文件名匹配模式
    FILE_PATTERN = r'([^\s，。？!！?？]+?\.(?:pdf|docx?|xlsx?|txt|md|pptx?))'

    # ==================== 检索策略模板 ====================
    SEARCH_STRATEGIES = {
        QueryType.SIMPLE: {
            "top_k": 5,
            "bm25_weight": 0.4,
            "vector_weight": 0.6,
            "rerank_candidates": 15,
            "rerank_top_k": 5,
            "max_iterations": 1
        },
        QueryType.FACT: {
            "top_k": 5,
            "bm25_weight": 0.4,
            "vector_weight": 0.6,
            "rerank_candidates": 20,
            "rerank_top_k": 5,
            "max_iterations": 2
        },
        QueryType.COMPARISON: {
            "top_k": 10,           # 更多候选
            "bm25_weight": 0.5,
            "vector_weight": 0.5,
            "rerank_candidates": 30,
            "rerank_top_k": 8,     # 返回更多
            "max_iterations": 2,
            "multi_kb": True       # 多库检索
        },
        QueryType.PROCESS: {
            "top_k": 8,
            "bm25_weight": 0.6,    # 关键词更重要
            "vector_weight": 0.4,
            "rerank_candidates": 25,
            "rerank_top_k": 6,
            "max_iterations": 2,
            "keyword_boost": True  # 关键词增强
        },
        QueryType.META: {
            "top_k": 0,            # 元问题不需要检索
            "max_iterations": 0
        },
        QueryType.REALTIME: {
            "top_k": 0,            # 实时信息走网络搜索
            "max_iterations": 0,
            "web_search": True
        },
        QueryType.FILE_SPECIFIC: {
            "top_k": 10,           # 文件特定查询，返回更多结果
            "bm25_weight": 0.3,
            "vector_weight": 0.7,
            "rerank_candidates": 20,
            "rerank_top_k": 10,
            "max_iterations": 1    # 单轮检索即可
        }
    }

    def __init__(self, custom_patterns: Dict[str, List[str]] = None):
        """
        初始化分类器

        Args:
            custom_patterns: 自定义规则关键词
                {"META": [...], "COMPARISON": [...], ...}
        """
        # 合并自定义规则
        if custom_patterns:
            if "META" in custom_patterns:
                self.META_PATTERNS = self.META_PATTERNS + custom_patterns["META"]
            if "REALTIME" in custom_patterns:
                self.REALTIME_PATTERNS = self.REALTIME_PATTERNS + custom_patterns["REALTIME"]
            if "COMPARISON" in custom_patterns:
                self.COMPARISON_PATTERNS = self.COMPARISON_PATTERNS + custom_patterns["COMPARISON"]
            if "PROCESS" in custom_patterns:
                self.PROCESS_PATTERNS = self.PROCESS_PATTERNS + custom_patterns["PROCESS"]
            if "BUSINESS" in custom_patterns:
                self.BUSINESS_KEYWORDS = self.BUSINESS_KEYWORDS + custom_patterns["BUSINESS"]

    def classify(self, query: str, history: List[dict] = None) -> ClassifiedQuery:
        """
        分类查询

        Args:
            query: 用户查询
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]

        Returns:
            ClassifiedQuery: 分类结果
        """
        original_query = query.strip()

        # 第一层：规则快速分类
        query_type, skip_llm = self._rule_based_classify(original_query)

        # 提取文件名（如果是文件特定查询）
        source_filter = None
        if query_type == QueryType.FILE_SPECIFIC:
            match = re.search(self.FILE_PATTERN, original_query, re.IGNORECASE)
            if match:
                source_filter = match.group(1)

        # 实体补全（利用对话历史）
        processed_query, entities = self._complete_entities(original_query, history)

        # 提取关键词
        keywords = self._extract_keywords(original_query)

        # 判断是否为简单查询（短查询 + 有明确主语）
        if query_type == QueryType.FACT:
            if self._is_simple_query(original_query, keywords):
                query_type = QueryType.SIMPLE
                skip_llm = True

        # 生成检索配置
        search_config = self._get_search_config(query_type)

        # 计算置信度
        confidence = 0.95 if skip_llm else 0.75

        return ClassifiedQuery(
            query_type=query_type,
            original_query=original_query,
            processed_query=processed_query,
            keywords=keywords,
            entities=entities,
            confidence=confidence,
            skip_llm_decision=skip_llm,
            search_config=search_config,
            source_filter=source_filter
        )

    def _rule_based_classify(self, query: str) -> tuple:
        """
        规则分类（无 LLM）

        Returns:
            (QueryType, skip_llm_decision)
        """
        # 元问题 - 直接回答，跳过检索
        if any(p in query for p in self.META_PATTERNS):
            return QueryType.META, True

        # 实时信息 - 网络搜索
        if any(p in query for p in self.REALTIME_PATTERNS):
            return QueryType.REALTIME, True

        # 文件特定查询 - 检测是否包含文件名
        if re.search(self.FILE_PATTERN, query, re.IGNORECASE):
            return QueryType.FILE_SPECIFIC, True

        # 比较分析 - 需要复杂检索
        if any(p in query for p in self.COMPARISON_PATTERNS):
            return QueryType.COMPARISON, False

        # 流程指引 - 关键词增强检索
        if any(p in query for p in self.PROCESS_PATTERNS):
            return QueryType.PROCESS, False

        # 默认：事实查询
        return QueryType.FACT, False

    def _is_simple_query(self, query: str, keywords: List[str]) -> bool:
        """
        判断是否为简单查询

        简单查询特征：
        - 长度较短（< 20 字符）
        - 有明确业务主语
        - 关键词数量少（<= 3）
        """
        if len(query) > 20:
            return False

        if not self._has_subject(query):
            return False

        if len(keywords) > 3:
            return False

        return True

    def _has_subject(self, query: str) -> bool:
        """判断查询是否有明确主语"""
        return any(kw in query for kw in self.BUSINESS_KEYWORDS)

    def _extract_keywords(self, query: str) -> List[str]:
        """
        提取关键词

        使用 jieba 分词，过滤停用词和短词
        """
        try:
            import jieba
        except ImportError:
            # jieba 未安装，使用简单分词
            return self._simple_tokenize(query)

        keywords = []
        for word in jieba.cut(query):
            word = word.strip()
            # 过滤条件：长度 >= 2，非停用词，非纯数字
            if (len(word) >= 2 and
                word not in self.STOP_WORDS and
                not word.isdigit() and
                not re.match(r'^[\d.]+$', word)):
                keywords.append(word)

        return list(set(keywords))

    def _simple_tokenize(self, query: str) -> List[str]:
        """简单分词（jieba 不可用时的降级方案）"""
        # 使用正则分割
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', query)
        return [w for w in words if len(w) >= 2 and w not in self.STOP_WORDS]

    def _complete_entities(self, query: str, history: List[dict] = None) -> tuple:
        """
        实体补全

        利用对话历史补全查询中缺失的主语

        Args:
            query: 当前查询
            history: 对话历史

        Returns:
            (processed_query, entities)
        """
        if not history:
            return query, []

        # 获取最近用户消息
        last_user_msg = self._get_last_user_msg(history)
        if not last_user_msg:
            return query, []

        # 如果当前查询有主语，不需要补全
        if self._has_subject(query):
            entities = self._extract_entities(last_user_msg)
            return query, entities

        # 提取上一轮实体
        entities = self._extract_entities(last_user_msg)
        if entities:
            # 实体补全
            processed_query = f"{query}（关于{entities[0]}）"
            return processed_query, entities

        return query, []

    def _get_last_user_msg(self, history: List[dict]) -> str:
        """获取最近用户消息"""
        for msg in reversed(history):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _extract_entities(self, text: str) -> List[str]:
        """
        提取实体

        简单实现：提取业务关键词作为实体
        """
        entities = []
        for kw in self.BUSINESS_KEYWORDS:
            if kw in text:
                entities.append(kw)
        return entities[:3]  # 最多返回 3 个

    def _get_search_config(self, query_type: QueryType) -> dict:
        """根据查询类型生成检索配置"""
        return self.SEARCH_STRATEGIES.get(query_type, self.SEARCH_STRATEGIES[QueryType.FACT]).copy()

    # ==================== 扩展接口 ====================

    def add_custom_patterns(self, category: str, patterns: List[str]):
        """
        添加自定义规则关键词

        Args:
            category: 类别名称 (META, REALTIME, COMPARISON, PROCESS, BUSINESS)
            patterns: 关键词列表
        """
        if category == "META":
            self.META_PATTERNS = self.META_PATTERNS + patterns
        elif category == "REALTIME":
            self.REALTIME_PATTERNS = self.REALTIME_PATTERNS + patterns
        elif category == "COMPARISON":
            self.COMPARISON_PATTERNS = self.COMPARISON_PATTERNS + patterns
        elif category == "PROCESS":
            self.PROCESS_PATTERNS = self.PROCESS_PATTERNS + patterns
        elif category == "BUSINESS":
            self.BUSINESS_KEYWORDS = self.BUSINESS_KEYWORDS + patterns

    def get_all_patterns(self) -> dict:
        """获取所有规则关键词（用于调试）"""
        return {
            "META": self.META_PATTERNS,
            "REALTIME": self.REALTIME_PATTERNS,
            "COMPARISON": self.COMPARISON_PATTERNS,
            "PROCESS": self.PROCESS_PATTERNS,
            "BUSINESS": self.BUSINESS_KEYWORDS
        }


# ==================== 便捷函数 ====================

def classify_query(query: str, history: List[dict] = None) -> ClassifiedQuery:
    """
    便捷函数：分类查询

    Args:
        query: 用户查询
        history: 对话历史

    Returns:
        ClassifiedQuery: 分类结果
    """
    classifier = QueryClassifier()
    return classifier.classify(query, history)


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    # 测试用例
    test_queries = [
        # 元问题
        ("有哪些文件可以查看？", QueryType.META),
        ("知识库里有什么？", QueryType.META),

        # 实时信息
        ("今天天气怎么样？", QueryType.REALTIME),
        ("最新新闻是什么？", QueryType.REALTIME),

        # 比较分析
        ("年假和病假有什么区别？", QueryType.COMPARISON),
        ("两种报销方式哪个更好？", QueryType.COMPARISON),

        # 流程指引
        ("请假流程是什么？", QueryType.PROCESS),
        ("怎么办理出差审批？", QueryType.PROCESS),

        # 简单查询
        ("报销标准", QueryType.SIMPLE),
        ("年假天数", QueryType.SIMPLE),

        # 事实查询
        ("出差补助标准是多少？", QueryType.FACT),
        ("公司规定员工试用期多长？", QueryType.FACT),
    ]

    classifier = QueryClassifier()

    print("=" * 60)
    print("查询分类器测试")
    print("=" * 60)

    for query, expected_type in test_queries:
        result = classifier.classify(query)
        status = "[OK]" if result.query_type == expected_type else "[FAIL]"
        print(f"\n{status} 查询: {query}")
        print(f"  类型: {result.query_type.value} (预期: {expected_type.value})")
        print(f"  跳过LLM: {result.skip_llm_decision}")
        print(f"  关键词: {result.keywords}")
        print(f"  检索配置: top_k={result.search_config.get('top_k', 'N/A')}")
