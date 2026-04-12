"""
知识库路由器 - 智能选择查询目标

功能：
1. 查询意图分析 - 判断查询是否涉及特定部门
2. 知识库路由 - 根据意图和权限选择目标向量库
3. 单库优化 - 如果只需查询单库，避免不必要的并行检索

使用方式：
    from kb_router import KnowledgeBaseRouter

    router = KnowledgeBaseRouter()

    # 获取目标向量库
    target_kbs = router.route(
        query="财务部的报销流程是什么",
        role="user",
        department="tech"
    )
    # 返回: ["public_kb", "dept_finance"]  # 如果有权限
"""

import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from openai import OpenAI

# 导入配置
try:
    from config import API_KEY, BASE_URL, MODEL
except ImportError:
    from rag_demo import API_KEY, BASE_URL, MODEL

# 导入权限管理
from auth_gateway import get_accessible_collections

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 部门关键词配置 ====================

# 部门关键词映射（可根据实际情况扩展）
DEPARTMENT_KEYWORDS = {
    "finance": [
        "财务", "报销", "发票", "预算", "支出", "收入", "成本",
        "账目", "会计", "审计", "税务", "工资", "奖金", "补贴",
        "费用", "付款", "收款", "借款", "报销单", "财务部"
    ],
    "hr": [
        "人事", "招聘", "入职", "离职", "考勤", "请假", "休假",
        "员工", "培训", "绩效", "晋升", "调岗", "合同", "档案",
        "社保", "公积金", "福利", "加班", "年假", "人事部", "人力资源"
    ],
    "tech": [
        "技术", "开发", "代码", "系统", "服务器", "数据库", "API",
        "接口", "部署", "测试", "Bug", "需求", "架构", "运维",
        "网络安全", "服务器", "云服务", "技术部", "研发", "IT"
    ],
    "operation": [
        "运营", "推广", "营销", "活动", "用户", "增长", "数据",
        "分析", "客服", "售后", "投诉", "反馈", "运营部", "运营中心"
    ],
    "marketing": [
        "市场", "品牌", "宣传", "广告", "公关", "媒体", "推广",
        "展会", "活动策划", "市场部", "营销部"
    ],
    "legal": [
        "法务", "合同", "法律", "诉讼", "合规", "风险", "版权",
        "知识产权", "协议", "法务部"
    ],
    "admin": [
        "行政", "办公室", "会议室", "采购", "固定资产", "办公用品",
        "印章", "档案", "行政部", "总务"
    ]
}

# 通用关键词（查询 public_kb）
GENERAL_KEYWORDS = [
    "公司", "企业", "组织", "介绍", "简介", "文化", "价值观",
    "制度", "规定", "流程", "政策", "手册", "指南", "帮助",
    "联系方式", "地址", "电话", "邮箱"
]


# ==================== 数据结构 ====================

@dataclass
class QueryIntent:
    """查询意图"""
    is_general: bool              # 是否为通用问题
    department: Optional[str]      # 涉及的部门（如果有）
    confidence: float             # 置信度
    keywords: List[str]           # 匹配到的关键词
    reason: str                   # 判断理由


# ==================== 知识库路由器 ====================

class KnowledgeBaseRouter:
    """
    知识库路由器

    根据查询内容和用户权限，智能选择需要查询的向量库。
    支持规则匹配和 LLM 意图分析两种方式。
    """

    def __init__(self, use_llm: bool = True):
        """
        初始化

        Args:
            use_llm: 是否使用 LLM 进行意图分析（更准确但更慢）
        """
        self.use_llm = use_llm
        self.llm_client = None

        if use_llm:
            try:
                self.llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
                logger.info("LLM 客户端初始化成功，将使用 LLM 进行意图分析")
            except Exception as e:
                logger.warning(f"LLM 客户端初始化失败: {e}，将使用规则匹配")
                self.use_llm = False

    def route(
        self,
        query: str,
        role: str,
        department: str,
        accessible_collections: List[str] = None
    ) -> List[str]:
        """
        根据查询意图和用户权限，决定查询哪些向量库

        Args:
            query: 用户查询
            role: 用户角色
            department: 用户部门
            accessible_collections: 可访问的向量库列表（可选）

        Returns:
            需要查询的向量库名称列表
        """
        # 1. 获取可访问的向量库
        if accessible_collections is None:
            accessible_collections = get_accessible_collections(role, department)

        if not accessible_collections:
            logger.warning(f"用户无可访问的向量库: role={role}, dept={department}")
            return []

        # 2. 分析查询意图
        intent = self.analyze_intent(query)

        # 3. 根据意图选择目标库
        target_kbs = self._select_knowledge_bases(
            intent, accessible_collections, role, department
        )

        logger.info(
            f"路由决策: query='{query[:30]}...', "
            f"intent={intent.department or 'general'}, "
            f"targets={target_kbs}"
        )

        return target_kbs

    def analyze_intent(self, query: str) -> QueryIntent:
        """
        分析查询意图

        Args:
            query: 用户查询

        Returns:
            QueryIntent 对象
        """
        # 先尝试规则匹配（快速）
        rule_intent = self._analyze_by_rules(query)

        # 如果规则匹配置信度高，直接返回
        if rule_intent.confidence > 0.8:
            return rule_intent

        # 否则使用 LLM 分析（更准确）
        if self.use_llm and self.llm_client:
            llm_intent = self._analyze_by_llm(query)
            if llm_intent:
                # 取两者中置信度高的
                return llm_intent if llm_intent.confidence > rule_intent.confidence else rule_intent

        return rule_intent

    def _analyze_by_rules(self, query: str) -> QueryIntent:
        """基于规则的意图分析"""
        query_lower = query.lower()
        matched_departments = {}
        matched_general = []

        # 检查部门关键词
        for dept, keywords in DEPARTMENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in query_lower:
                    if dept not in matched_departments:
                        matched_departments[dept] = []
                    matched_departments[dept].append(keyword)

        # 检查通用关键词
        for keyword in GENERAL_KEYWORDS:
            if keyword in query_lower:
                matched_general.append(keyword)

        # 判断结果
        if matched_departments:
            # 找到匹配最多的部门
            best_dept = max(
                matched_departments.keys(),
                key=lambda d: len(matched_departments[d])
            )
            keywords = matched_departments[best_dept]
            confidence = min(0.9, 0.5 + len(keywords) * 0.1)

            return QueryIntent(
                is_general=False,
                department=best_dept,
                confidence=confidence,
                keywords=keywords,
                reason=f"匹配到部门关键词: {', '.join(keywords)}"
            )

        elif matched_general:
            return QueryIntent(
                is_general=True,
                department=None,
                confidence=0.7,
                keywords=matched_general,
                reason=f"匹配到通用关键词: {', '.join(matched_general)}"
            )

        else:
            return QueryIntent(
                is_general=False,
                department=None,
                confidence=0.3,
                keywords=[],
                reason="未匹配到关键词，需要查询所有可访问的库"
            )

    def _analyze_by_llm(self, query: str) -> Optional[QueryIntent]:
        """使用 LLM 进行意图分析"""
        try:
            prompt = f"""分析以下问题的意图，判断：

1. 是否为通用问题（涉及公司整体、产品、文化等，不特指某部门）
2. 是否涉及特定部门（财务、人事、技术等）

问题：{query}

请直接返回 JSON 格式（不要包含其他内容）：
{{"is_general": true/false, "department": "部门英文名或null", "confidence": 0.0-1.0}}

部门英文名对照：
- finance: 财务
- hr: 人事
- tech: 技术
- operation: 运营
- marketing: 市场
- legal: 法务
- admin: 行政

注意：
- 如果问题涉及多个部门，返回 null
- 如果问题明显指向某个部门，返回对应英文名
- confidence 表示判断置信度，0-1之间"""

            response = self.llm_client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=100
            )

            content = response.choices[0].message.content.strip()

            # 尝试解析 JSON
            # 移除可能的 markdown 代码块标记
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)

            result = json.loads(content)

            return QueryIntent(
                is_general=result.get("is_general", False),
                department=result.get("department"),
                confidence=result.get("confidence", 0.5),
                keywords=[],
                reason="LLM 意图分析"
            )

        except Exception as e:
            logger.warning(f"LLM 意图分析失败: {e}")
            return None

    def _select_knowledge_bases(
        self,
        intent: QueryIntent,
        accessible_collections: List[str],
        role: str,
        department: str
    ) -> List[str]:
        """
        选择要查询的知识库

        Args:
            intent: 查询意图
            accessible_collections: 可访问的向量库
            role: 用户角色
            department: 用户部门

        Returns:
            目标向量库列表
        """
        result = []
        public_kb = "public_kb"

        # 通用问题：优先查 public_kb
        if intent.is_general:
            if public_kb in accessible_collections:
                result.append(public_kb)
            # 但也可能需要查其他库（取决于置信度）
            if intent.confidence < 0.7:
                result.extend([kb for kb in accessible_collections if kb not in result])

        # 涉及特定部门
        elif intent.department:
            dept_kb = f"dept_{intent.department}"

            # 检查是否有权限访问该部门
            if dept_kb in accessible_collections:
                result.append(dept_kb)
                # 也查 public_kb（可能有相关政策）
                if public_kb in accessible_collections and public_kb not in result:
                    result.append(public_kb)
            else:
                # 没有权限访问目标部门，查 public_kb
                if public_kb in accessible_collections:
                    result.append(public_kb)
                logger.info(
                    f"用户无权访问部门 {intent.department} 的知识库，"
                    f"只查 public_kb"
                )

        # 未识别意图
        else:
            # admin 查所有
            if role == "admin":
                result = accessible_collections
            # 其他用户查 public 和本部门
            else:
                if public_kb in accessible_collections:
                    result.append(public_kb)
                user_dept_kb = f"dept_{department}"
                if user_dept_kb in accessible_collections and user_dept_kb not in result:
                    result.append(user_dept_kb)

        # 去重并保持顺序
        seen = set()
        unique_result = []
        for kb in result:
            if kb not in seen:
                seen.add(kb)
                unique_result.append(kb)

        return unique_result

    def get_routing_stats(self) -> Dict:
        """获取路由统计信息（用于监控）"""
        return {
            "use_llm": self.use_llm,
            "department_keywords": {
                dept: len(keywords)
                for dept, keywords in DEPARTMENT_KEYWORDS.items()
            },
            "general_keywords_count": len(GENERAL_KEYWORDS)
        }

    # ==================== 版本感知检索 ====================

    def route_with_version_awareness(
        self,
        query: str,
        role: str,
        department: str,
        accessible_collections: List[str] = None,
        include_deprecated: bool = False,
        top_k: int = 5
    ) -> Dict:
        """
        版本感知的路由

        在普通路由基础上，额外查询已废止的相关文档，
        为用户提供版本提示。

        Args:
            query: 用户查询
            role: 用户角色
            department: 用户部门
            accessible_collections: 可访问的向量库列表
            include_deprecated: 是否包含废止版本在结果中
            top_k: 返回数量

        Returns:
            {
                "target_collections": ["public_kb", "dept_finance"],
                "version_hints": [
                    {
                        "document": "报销制度.pdf",
                        "status": "deprecated",
                        "message": "该文档已于2026-03-01废止"
                    }
                ]
            }
        """
        # 1. 获取目标向量库（复用现有逻辑）
        target_kbs = self.route(query, role, department, accessible_collections)

        if not target_kbs:
            return {
                "target_collections": [],
                "version_hints": []
            }

        # 2. 查询是否有相关的废止版本
        version_hints = []
        if not include_deprecated:
            version_hints = self._find_deprecated_versions(query, target_kbs, top_k=3)

        logger.info(
            f"版本感知路由: query='{query[:30]}...', "
            f"targets={target_kbs}, hints={len(version_hints)}"
        )

        return {
            "target_collections": target_kbs,
            "version_hints": version_hints
        }

    def _find_deprecated_versions(
        self,
        query: str,
        collections: List[str],
        top_k: int = 3
    ) -> List[Dict]:
        """
        查找与查询相关的已废止版本

        Args:
            query: 用户查询
            collections: 目标向量库列表
            top_k: 每个库返回数量

        Returns:
            已废止版本提示列表
        """
        try:
            from knowledge_base_manager import get_kb_manager

            kb_manager = get_kb_manager()

            # 获取查询向量
            query_vector = self._get_query_vector(query)
            if query_vector is None:
                return []

            # 使用知识库管理器查找废止版本
            hints = kb_manager.find_deprecated_versions(
                kb_names=collections,
                query_vector=query_vector,
                top_k=top_k
            )

            # 去重（同一文档只提示一次）
            seen_docs = set()
            unique_hints = []
            for hint in hints:
                doc_key = f"{hint['collection']}/{hint['document']}"
                if doc_key not in seen_docs:
                    seen_docs.add(doc_key)
                    unique_hints.append(hint)

            return unique_hints

        except Exception as e:
            logger.warning(f"查找废止版本失败: {e}")
            return []

    def _get_query_vector(self, query: str) -> Optional[List[float]]:
        """
        获取查询向量

        Args:
            query: 查询文本

        Returns:
            查询向量，失败返回None
        """
        try:
            # 尝试使用 rag_demo 的 embedding_model
            from rag_demo import embedding_model
            return embedding_model.encode(query).tolist()
        except ImportError:
            pass

        try:
            # 尝试使用 sentence-transformers
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('BAAI/bge-base-zh-v1.5')
            return model.encode(query).tolist()
        except Exception:
            pass

        logger.warning("无法加载向量模型，跳过废止版本检测")
        return None

    def search_with_version_context(
        self,
        query: str,
        role: str,
        department: str,
        top_k: int = 5
    ) -> Dict:
        """
        带版本上下文的搜索

        执行完整搜索流程：
        1. 版本感知路由
        2. 执行检索（只返回生效版本）
        3. 返回结果 + 废止版本提示

        Args:
            query: 用户查询
            role: 用户角色
            department: 用户部门
            top_k: 返回数量

        Returns:
            {
                "results": [...],  # 生效版本的检索结果
                "version_hints": [...],  # 废止版本提示
                "target_collections": [...]
            }
        """
        from knowledge_base_manager import get_kb_manager

        kb_manager = get_kb_manager()

        # 1. 版本感知路由
        route_result = self.route_with_version_awareness(
            query, role, department, include_deprecated=False
        )

        target_kbs = route_result["target_collections"]
        version_hints = route_result["version_hints"]

        if not target_kbs:
            return {
                "results": [],
                "version_hints": version_hints,
                "target_collections": []
            }

        # 2. 执行检索（只返回生效版本）
        query_vector = self._get_query_vector(query)
        if query_vector is None:
            return {
                "results": [],
                "version_hints": version_hints,
                "target_collections": target_kbs
            }

        # 多库检索，只返回active状态的chunks
        search_result = kb_manager.search_multiple(
            kb_names=target_kbs,
            query_vector=query_vector,
            query_text=query,
            top_k=top_k,
            use_bm25=True
        )

        # 过滤只返回active状态的chunks
        active_results = []
        if search_result.ids:
            for i, (doc_id, doc, meta, score) in enumerate(zip(
                search_result.ids,
                search_result.documents,
                search_result.metadatas,
                search_result.distances
            )):
                if meta.get("status", "active") == "active":
                    active_results.append({
                        "id": doc_id,
                        "document": doc,
                        "metadata": meta,
                        "score": score
                    })

        return {
            "results": active_results[:top_k],
            "version_hints": version_hints,
            "target_collections": target_kbs
        }


# ==================== 全局实例 ====================

_kb_router: Optional[KnowledgeBaseRouter] = None


def get_kb_router() -> KnowledgeBaseRouter:
    """获取全局知识库路由器实例"""
    global _kb_router
    if _kb_router is None:
        _kb_router = KnowledgeBaseRouter()
    return _kb_router


# ==================== 便捷函数 ====================

def route_query(
    query: str,
    role: str,
    department: str,
    accessible_collections: List[str] = None
) -> List[str]:
    """
    路由查询到目标知识库（便捷函数）

    Args:
        query: 用户查询
        role: 用户角色
        department: 用户部门
        accessible_collections: 可访问的向量库列表

    Returns:
        目标向量库列表
    """
    router = get_kb_router()
    return router.route(query, role, department, accessible_collections)


def route_query_with_version(
    query: str,
    role: str,
    department: str,
    accessible_collections: List[str] = None,
    include_deprecated: bool = False
) -> Dict:
    """
    版本感知的路由（便捷函数）

    Args:
        query: 用户查询
        role: 用户角色
        department: 用户部门
        accessible_collections: 可访问的向量库列表
        include_deprecated: 是否包含废止版本

    Returns:
        {
            "target_collections": [...],
            "version_hints": [...]
        }
    """
    router = get_kb_router()
    return router.route_with_version_awareness(
        query, role, department, accessible_collections, include_deprecated
    )


def search_with_version_context(
    query: str,
    role: str,
    department: str,
    top_k: int = 5
) -> Dict:
    """
    带版本上下文的搜索（便捷函数）

    Args:
        query: 用户查询
        role: 用户角色
        department: 用户部门
        top_k: 返回数量

    Returns:
        {
            "results": [...],
            "version_hints": [...],
            "target_collections": [...]
        }
    """
    router = get_kb_router()
    return router.search_with_version_context(query, role, department, top_k)
