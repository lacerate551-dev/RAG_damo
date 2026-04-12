"""
题库维护与整卷分析服务

功能：
1. GKPT-EXAM-009 题库智能维护
   - 题目-制度关联表
   - 制度版本追踪
   - 受影响题目检测
   - 新题生成建议

2. GKPT-EXAM-018 整卷评语分析
   - 整卷答题情况分析
   - 知识点映射表
   - 薄弱点识别算法
   - AI评语生成
   - 学习建议生成
"""

import json
import os
import sqlite3
import hashlib
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 枚举定义 ====================

class QuestionStatus(Enum):
    """题目状态"""
    DRAFT = "draft"                    # 草稿
    PENDING_REVIEW = "pending_review"  # 待审核
    APPROVED = "approved"              # 已通过
    AFFECTED = "affected"              # 受影响待审核
    DEPRECATED = "deprecated"          # 已过期
    DISABLED = "disabled"              # 已禁用


class ChangeImpact(Enum):
    """变更影响程度"""
    HIGH = "high"      # 高影响 - 核心内容变更
    MEDIUM = "medium"  # 中影响 - 部分内容变更
    LOW = "low"        # 低影响 - 格式/错别字修正


# ==================== 数据类定义 ====================

@dataclass
class QuestionDocumentLink:
    """题目-制度关联"""
    id: Optional[int] = None
    question_id: str = ""
    question_type: str = ""  # choice/blank/short_answer
    exam_id: str = ""
    document_id: str = ""    # 制度文档ID
    document_name: str = ""  # 制度文档名称
    chapter: str = ""        # 关联章节
    key_points: List[str] = None  # 关联知识点
    relevance_score: float = 0.0  # 相关性分数
    created_at: str = ""

    def __post_init__(self):
        if self.key_points is None:
            self.key_points = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class DocumentVersion:
    """制度版本"""
    id: Optional[int] = None
    document_id: str = ""
    version: str = ""
    content_hash: str = ""
    change_summary: str = ""       # AI生成的变更摘要
    changed_sections: List[str] = None  # 变更的章节列表
    created_at: str = ""

    def __post_init__(self):
        if self.changed_sections is None:
            self.changed_sections = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class KnowledgePoint:
    """知识点"""
    id: Optional[int] = None
    name: str = ""
    category: str = ""       # 分类
    description: str = ""    # 描述
    parent_id: Optional[int] = None  # 父知识点ID
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class QuestionKnowledgeLink:
    """题目-知识点关联"""
    id: Optional[int] = None
    question_id: str = ""
    question_type: str = ""
    exam_id: str = ""
    knowledge_point_id: int = 0
    knowledge_point_name: str = ""
    weight: float = 1.0  # 权重
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class ExamAnalysisReport:
    """整卷分析报告"""
    report_id: str = ""
    exam_id: str = ""
    exam_name: str = ""
    student_name: str = ""
    total_score: float = 0.0
    max_score: float = 0.0
    score_rate: float = 0.0

    # 各题型得分
    type_scores: Dict[str, Dict] = None  # {type: {score, max, rate}}

    # 知识点分析
    knowledge_analysis: List[Dict] = None  # [{name, score, max, rate}]

    # 薄弱知识点
    weak_points: List[Dict] = None   # [{name, score_rate, suggestions}]

    # 掌握较好的知识点
    strong_points: List[Dict] = None

    # AI评语
    ai_comment: str = ""

    # 学习建议
    study_suggestions: List[Dict] = None  # [{point, document, suggestion}]

    created_at: str = ""

    def __post_init__(self):
        if self.type_scores is None:
            self.type_scores = {}
        if self.knowledge_analysis is None:
            self.knowledge_analysis = []
        if self.weak_points is None:
            self.weak_points = []
        if self.strong_points is None:
            self.strong_points = []
        if self.study_suggestions is None:
            self.study_suggestions = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


# ==================== 数据库管理 ====================

class ExamAnalysisDB:
    """题库分析数据库"""

    def __init__(self, db_path: str = "./data/exam_analysis.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 题目-制度关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_document_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL,
                question_type TEXT NOT NULL,
                exam_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_name TEXT,
                chapter TEXT,
                key_points TEXT,  -- JSON格式
                relevance_score REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 制度版本表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                version TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                change_summary TEXT,
                changed_sections TEXT,  -- JSON格式
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 知识点表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT,
                description TEXT,
                parent_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES knowledge_points(id)
            )
        """)

        # 题目-知识点关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_knowledge_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL,
                question_type TEXT NOT NULL,
                exam_id TEXT NOT NULL,
                knowledge_point_id INTEGER NOT NULL,
                knowledge_point_name TEXT,
                weight REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
            )
        """)

        # 题目状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL UNIQUE,
                question_type TEXT NOT NULL,
                exam_id TEXT NOT NULL,
                status TEXT DEFAULT 'approved',
                affected_by TEXT,  -- 影响该题目的制度ID
                affect_reason TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 整卷分析报告表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_analysis_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL UNIQUE,
                exam_id TEXT,
                exam_name TEXT,
                student_name TEXT,
                total_score REAL,
                max_score REAL,
                score_rate REAL,
                type_scores TEXT,  -- JSON格式
                knowledge_analysis TEXT,  -- JSON格式
                weak_points TEXT,  -- JSON格式
                strong_points TEXT,  -- JSON格式
                ai_comment TEXT,
                study_suggestions TEXT,  -- JSON格式
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 新题建议表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                suggestion TEXT,  -- JSON格式的建议题目
                status TEXT DEFAULT 'pending',  -- pending/approved/rejected
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qdl_question ON question_document_links(question_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qdl_document ON question_document_links(document_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qkl_question ON question_knowledge_links(question_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qkl_knowledge ON question_knowledge_links(knowledge_point_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qs_status ON question_status(status)")

        conn.commit()
        conn.close()

    # ==================== 题目-制度关联 ====================

    def add_question_document_link(self, link: QuestionDocumentLink) -> int:
        """添加题目-制度关联"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO question_document_links
            (question_id, question_type, exam_id, document_id, document_name,
             chapter, key_points, relevance_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            link.question_id, link.question_type, link.exam_id,
            link.document_id, link.document_name, link.chapter,
            json.dumps(link.key_points, ensure_ascii=False),
            link.relevance_score, link.created_at
        ))

        link_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return link_id

    def get_question_documents(self, question_id: str, question_type: str = None) -> List[Dict]:
        """获取题目关联的制度文档"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if question_type:
            cursor.execute("""
                SELECT * FROM question_document_links
                WHERE question_id = ? AND question_type = ?
            """, (question_id, question_type))
        else:
            cursor.execute("""
                SELECT * FROM question_document_links WHERE question_id = ?
            """, (question_id,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            if item.get('key_points'):
                item['key_points'] = json.loads(item['key_points'])
            results.append(item)

        return results

    def get_document_questions(self, document_id: str) -> List[Dict]:
        """获取制度文档关联的题目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM question_document_links WHERE document_id = ?
        """, (document_id,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            if item.get('key_points'):
                item['key_points'] = json.loads(item['key_points'])
            results.append(item)

        return results

    # ==================== 制度版本 ====================

    def add_document_version(self, version: DocumentVersion) -> int:
        """添加制度版本"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO document_versions
            (document_id, version, content_hash, change_summary, changed_sections, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            version.document_id, version.version, version.content_hash,
            version.change_summary,
            json.dumps(version.changed_sections, ensure_ascii=False),
            version.created_at
        ))

        version_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return version_id

    def get_document_versions(self, document_id: str, limit: int = 10) -> List[Dict]:
        """获取制度版本历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM document_versions
            WHERE document_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (document_id, limit))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            if item.get('changed_sections'):
                item['changed_sections'] = json.loads(item['changed_sections'])
            results.append(item)

        return results

    def get_latest_version(self, document_id: str) -> Optional[Dict]:
        """获取最新版本"""
        versions = self.get_document_versions(document_id, limit=1)
        return versions[0] if versions else None

    # ==================== 知识点 ====================

    def add_knowledge_point(self, point: KnowledgePoint) -> int:
        """添加知识点"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO knowledge_points (name, category, description, parent_id, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (point.name, point.category, point.description, point.parent_id, point.created_at))

            point_id = cursor.lastrowid
            conn.commit()
        except sqlite3.IntegrityError:
            # 已存在，返回现有ID
            cursor.execute("SELECT id FROM knowledge_points WHERE name = ?", (point.name,))
            point_id = cursor.fetchone()[0]
        finally:
            conn.close()

        return point_id

    def get_knowledge_points(self, category: str = None) -> List[Dict]:
        """获取知识点列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if category:
            cursor.execute("""
                SELECT * FROM knowledge_points WHERE category = ? ORDER BY name
            """, (category,))
        else:
            cursor.execute("SELECT * FROM knowledge_points ORDER BY name")

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    def add_question_knowledge_link(self, link: QuestionKnowledgeLink) -> int:
        """添加题目-知识点关联"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO question_knowledge_links
            (question_id, question_type, exam_id, knowledge_point_id,
             knowledge_point_name, weight, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            link.question_id, link.question_type, link.exam_id,
            link.knowledge_point_id, link.knowledge_point_name,
            link.weight, link.created_at
        ))

        link_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return link_id

    def get_question_knowledge_points(self, question_id: str) -> List[Dict]:
        """获取题目关联的知识点"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM question_knowledge_links WHERE question_id = ?
        """, (question_id,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    # ==================== 题目状态 ====================

    def update_question_status(self, question_id: str, question_type: str,
                               exam_id: str, status: str, affected_by: str = None,
                               affect_reason: str = None):
        """更新题目状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO question_status
            (question_id, question_type, exam_id, status, affected_by, affect_reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            question_id, question_type, exam_id, status,
            affected_by, affect_reason, datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def get_affected_questions(self, document_id: str = None) -> List[Dict]:
        """获取受影响的题目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if document_id:
            cursor.execute("""
                SELECT * FROM question_status
                WHERE status = 'affected' AND affected_by = ?
            """, (document_id,))
        else:
            cursor.execute("""
                SELECT * FROM question_status WHERE status = 'affected'
            """)

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    # ==================== 分析报告 ====================

    def save_analysis_report(self, report: ExamAnalysisReport) -> str:
        """保存分析报告"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO exam_analysis_reports
            (report_id, exam_id, exam_name, student_name, total_score, max_score,
             score_rate, type_scores, knowledge_analysis, weak_points, strong_points,
             ai_comment, study_suggestions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report.report_id, report.exam_id, report.exam_name,
            report.student_name, report.total_score, report.max_score,
            report.score_rate,
            json.dumps(report.type_scores, ensure_ascii=False),
            json.dumps(report.knowledge_analysis, ensure_ascii=False),
            json.dumps(report.weak_points, ensure_ascii=False),
            json.dumps(report.strong_points, ensure_ascii=False),
            report.ai_comment,
            json.dumps(report.study_suggestions, ensure_ascii=False),
            report.created_at
        ))

        conn.commit()
        conn.close()
        return report.report_id

    def get_analysis_report(self, report_id: str) -> Optional[Dict]:
        """获取分析报告"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM exam_analysis_reports WHERE report_id = ?
        """, (report_id,))

        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))
        conn.close()

        # 解析JSON字段
        for field in ['type_scores', 'knowledge_analysis', 'weak_points',
                      'strong_points', 'study_suggestions']:
            if result.get(field):
                result[field] = json.loads(result[field])

        return result

    def list_analysis_reports(self, exam_id: str = None, limit: int = 20) -> List[Dict]:
        """获取分析报告列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if exam_id:
            cursor.execute("""
                SELECT report_id, exam_id, exam_name, student_name, total_score,
                       max_score, score_rate, created_at
                FROM exam_analysis_reports
                WHERE exam_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (exam_id, limit))
        else:
            cursor.execute("""
                SELECT report_id, exam_id, exam_name, student_name, total_score,
                       max_score, score_rate, created_at
                FROM exam_analysis_reports
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    # ==================== 新题建议 ====================

    def add_question_suggestion(self, document_id: str, suggestion: Dict) -> int:
        """添加新题建议"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO question_suggestions (document_id, suggestion, status, created_at)
            VALUES (?, ?, 'pending', ?)
        """, (document_id, json.dumps(suggestion, ensure_ascii=False),
              datetime.now().isoformat()))

        suggestion_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return suggestion_id

    def get_question_suggestions(self, document_id: str = None,
                                  status: str = None) -> List[Dict]:
        """获取新题建议"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        conditions = []
        params = []

        if document_id:
            conditions.append("document_id = ?")
            params.append(document_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor.execute(f"""
            SELECT * FROM question_suggestions WHERE {where_clause} ORDER BY created_at DESC
        """, params)

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            if item.get('suggestion'):
                item['suggestion'] = json.loads(item['suggestion'])
            results.append(item)

        return results

    def update_suggestion_status(self, suggestion_id: int, status: str):
        """更新建议状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE question_suggestions SET status = ? WHERE id = ?
        """, (status, suggestion_id))

        conn.commit()
        conn.close()


# ==================== 题库维护服务 ====================

class QuestionMaintenanceService:
    """题库智能维护服务"""

    def __init__(self, db: ExamAnalysisDB, rag_module=None):
        self.db = db
        self.rag_module = rag_module  # RAG模块用于AI分析

    def link_question_to_document(self, question_id: str, question_type: str,
                                   exam_id: str, document_id: str,
                                   document_name: str = "",
                                   chapter: str = "",
                                   key_points: List[str] = None,
                                   relevance_score: float = 1.0) -> int:
        """
        建立题目-制度关联

        Args:
            question_id: 题目ID
            question_type: 题型 (choice/blank/short_answer)
            exam_id: 试卷ID
            document_id: 制度文档ID
            document_name: 制度文档名称
            chapter: 关联章节
            key_points: 关联知识点
            relevance_score: 相关性分数

        Returns:
            关联ID
        """
        link = QuestionDocumentLink(
            question_id=question_id,
            question_type=question_type,
            exam_id=exam_id,
            document_id=document_id,
            document_name=document_name,
            chapter=chapter,
            key_points=key_points or [],
            relevance_score=relevance_score
        )
        return self.db.add_question_document_link(link)

    def link_question_to_knowledge(self, question_id: str, question_type: str,
                                    exam_id: str, knowledge_point: str,
                                    weight: float = 1.0) -> int:
        """
        建立题目-知识点关联

        Args:
            question_id: 题目ID
            question_type: 题型
            exam_id: 试卷ID
            knowledge_point: 知识点名称
            weight: 权重

        Returns:
            关联ID
        """
        # 确保知识点存在
        point = KnowledgePoint(name=knowledge_point)
        point_id = self.db.add_knowledge_point(point)

        link = QuestionKnowledgeLink(
            question_id=question_id,
            question_type=question_type,
            exam_id=exam_id,
            knowledge_point_id=point_id,
            knowledge_point_name=knowledge_point,
            weight=weight
        )
        return self.db.add_question_knowledge_link(link)

    def on_document_change(self, document_id: str, old_content: str = None,
                           new_content: str = None,
                           change_summary: str = None) -> Dict:
        """
        制度变更时的处理流程

        Args:
            document_id: 制度文档ID
            old_content: 旧内容（可选）
            new_content: 新内容（可选）
            change_summary: 变更摘要（可选）

        Returns:
            {
                'affected_questions': [...],
                'suggestions': [...]
            }
        """
        result = {
            'affected_questions': [],
            'suggestions': []
        }

        # 1. 获取关联题目
        linked_questions = self.db.get_document_questions(document_id)
        logger.info(f"制度 {document_id} 关联了 {len(linked_questions)} 道题目")

        # 2. 标记受影响的题目
        for q in linked_questions:
            self.db.update_question_status(
                question_id=q['question_id'],
                question_type=q['question_type'],
                exam_id=q['exam_id'],
                status=QuestionStatus.AFFECTED.value,
                affected_by=document_id,
                affect_reason="关联的制度文档已更新，需要审核"
            )
            result['affected_questions'].append({
                'question_id': q['question_id'],
                'question_type': q['question_type'],
                'exam_id': q['exam_id'],
                'document_name': q.get('document_name', ''),
                'chapter': q.get('chapter', '')
            })

        # 3. 生成新题建议（如果有新内容）
        if new_content:
            suggestions = self._generate_question_suggestions(document_id, new_content)
            result['suggestions'] = suggestions

        # 4. 记录版本
        if change_summary:
            version = DocumentVersion(
                document_id=document_id,
                version=datetime.now().strftime("%Y%m%d%H%M%S"),
                content_hash=hashlib.md5(new_content.encode()).hexdigest() if new_content else "",
                change_summary=change_summary,
                changed_sections=[]  # 可以通过AI分析提取变更章节
            )
            self.db.add_document_version(version)

        return result

    def _generate_question_suggestions(self, document_id: str,
                                        content: str) -> List[Dict]:
        """
        根据制度内容生成新题建议

        Args:
            document_id: 制度文档ID
            content: 制度内容

        Returns:
            新题建议列表
        """
        suggestions = []

        # 使用现有的 LLM 客户端生成建议
        try:
            from config import API_KEY, BASE_URL, MODEL
            from openai import OpenAI

            client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

            prompt = f"""基于以下制度内容，建议3-5道可能的考题。

制度内容：
{content[:3000]}

要求：
1. 题目应围绕制度的核心要点和易错点
2. 难度适中，适合企业内部培训考核
3. 包含选择题、填空题、简答题等多种题型

请以JSON格式返回，格式如下：
{{
    "suggestions": [
        {{
            "type": "choice",
            "content": "题目内容",
            "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
            "answer": "A",
            "difficulty": 3,
            "key_points": ["知识点1"],
            "explanation": "答案解析"
        }},
        {{
            "type": "blank",
            "content": "题目内容，___处填空",
            "answer": "答案",
            "difficulty": 2,
            "key_points": ["知识点1"]
        }},
        {{
            "type": "short_answer",
            "content": "题目内容",
            "reference_answer": "参考答案要点",
            "difficulty": 4,
            "key_points": ["知识点1", "知识点2"],
            "scoring_points": ["要点1: 2分", "要点2: 3分"]
        }}
    ]
}}

请只返回JSON，不要有其他内容。"""

            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=2000
            )

            result_text = response.choices[0].message.content.strip()

            # 解析JSON
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()

            result = json.loads(result_text)
            suggestions = result.get("suggestions", [])

            logger.info(f"为制度 {document_id} 生成了 {len(suggestions)} 条新题建议")

        except ImportError:
            logger.warning("未找到 LLM 配置，跳过新题生成")
        except Exception as e:
            logger.error(f"生成新题建议失败: {e}")

        # 保存建议到数据库
        for suggestion in suggestions:
            self.db.add_question_suggestion(document_id, suggestion)

        return suggestions

    def get_affected_questions(self, document_id: str = None) -> List[Dict]:
        """获取受影响的题目列表"""
        return self.db.get_affected_questions(document_id)

    def review_affected_question(self, question_id: str, question_type: str,
                                  exam_id: str, action: str) -> Dict:
        """
        审核受影响的题目

        Args:
            question_id: 题目ID
            question_type: 题型
            exam_id: 试卷ID
            action: 审核动作 (confirm/update/disable)

        Returns:
            审核结果
        """
        status_map = {
            'confirm': QuestionStatus.APPROVED.value,  # 确认有效
            'update': QuestionStatus.PENDING_REVIEW.value,  # 需要更新
            'disable': QuestionStatus.DISABLED.value  # 禁用
        }

        new_status = status_map.get(action, QuestionStatus.APPROVED.value)
        self.db.update_question_status(question_id, question_type, exam_id, new_status)

        return {
            'question_id': question_id,
            'action': action,
            'new_status': new_status,
            'success': True
        }


# ==================== 整卷分析服务 ====================

class ExamAnalysisService:
    """整卷评语分析服务"""

    def __init__(self, db: ExamAnalysisDB, rag_module=None, llm_client=None):
        self.db = db
        self.rag_module = rag_module
        self.llm_client = llm_client  # LLM客户端用于生成AI评语

    def analyze_exam_paper(self, grade_report: Dict,
                           question_knowledge_map: Dict = None) -> ExamAnalysisReport:
        """
        整卷分析

        Args:
            grade_report: 批阅报告（来自exam_manager.grade_exam）
            question_knowledge_map: 题目-知识点映射
                格式: {question_id: [{name, weight}]}

        Returns:
            ExamAnalysisReport
        """
        import uuid

        report = ExamAnalysisReport(
            report_id=str(uuid.uuid4()),
            exam_id=grade_report.get('exam_id', ''),
            exam_name=grade_report.get('exam_name', ''),
            student_name=grade_report.get('student_name', ''),
            total_score=grade_report.get('total_score', 0),
            max_score=grade_report.get('max_score', 100),
            score_rate=grade_report.get('score_rate', 0)
        )

        # 1. 分析各题型得分
        report.type_scores = self._analyze_type_scores(grade_report)

        # 2. 分析知识点掌握情况
        report.knowledge_analysis = self._analyze_knowledge_points(
            grade_report, question_knowledge_map
        )

        # 3. 识别薄弱知识点
        report.weak_points = self._identify_weak_points(report.knowledge_analysis)

        # 4. 识别优势知识点
        report.strong_points = self._identify_strong_points(report.knowledge_analysis)

        # 5. 生成AI评语
        report.ai_comment = self._generate_ai_comment(report)

        # 6. 生成学习建议
        report.study_suggestions = self._generate_study_suggestions(
            report.weak_points, question_knowledge_map
        )

        # 保存报告
        self.db.save_analysis_report(report)

        return report

    def _analyze_type_scores(self, grade_report: Dict) -> Dict:
        """分析各题型得分"""
        type_scores = {
            'choice': {'score': 0, 'max': 0, 'count': 0, 'correct': 0, 'partial': 0},
            'blank': {'score': 0, 'max': 0, 'count': 0, 'correct': 0, 'partial': 0},
            'short_answer': {'score': 0, 'max': 0, 'count': 0, 'correct': 0, 'partial': 0}
        }

        for q in grade_report.get('questions', []):
            q_type = q.get('type', 'choice')
            if q_type in type_scores:
                type_scores[q_type]['score'] += q.get('score', 0)
                type_scores[q_type]['max'] += q.get('max_score', 0)
                type_scores[q_type]['count'] += 1
                if q.get('correct', False) or q.get('score', 0) >= q.get('max_score', 0):
                    type_scores[q_type]['correct'] += 1
                elif q.get('score', 0) > 0:
                    type_scores[q_type]['partial'] += 1

        # 计算得分率
        for t in type_scores:
            if type_scores[t]['max'] > 0:
                type_scores[t]['rate'] = round(
                    type_scores[t]['score'] / type_scores[t]['max'] * 100, 1
                )
            else:
                type_scores[t]['rate'] = 0

        return type_scores

    def _analyze_knowledge_points(self, grade_report: Dict,
                                   question_knowledge_map: Dict = None) -> List[Dict]:
        """分析知识点掌握情况"""
        if not question_knowledge_map:
            return []

        knowledge_scores = {}  # {name: {score, max, count}}

        for q in grade_report.get('questions', []):
            q_id = str(q.get('id', ''))
            q_type = q.get('type', '')

            # 查找题目的知识点
            key = f"{q_type}_{q_id}"
            if key in question_knowledge_map:
                for kp in question_knowledge_map[key]:
                    kp_name = kp.get('name', '')
                    weight = kp.get('weight', 1.0)

                    if kp_name not in knowledge_scores:
                        knowledge_scores[kp_name] = {
                            'name': kp_name,
                            'score': 0,
                            'max': 0,
                            'count': 0
                        }

                    knowledge_scores[kp_name]['score'] += q.get('score', 0) * weight
                    knowledge_scores[kp_name]['max'] += q.get('max_score', 0) * weight
                    knowledge_scores[kp_name]['count'] += 1

        # 计算得分率并排序
        results = []
        for name, data in knowledge_scores.items():
            data['rate'] = round(data['score'] / data['max'] * 100, 1) if data['max'] > 0 else 0
            results.append(data)

        results.sort(key=lambda x: x['rate'])
        return results

    def _identify_weak_points(self, knowledge_analysis: List[Dict],
                               threshold: float = 60.0) -> List[Dict]:
        """识别薄弱知识点（得分率低于阈值）"""
        weak_points = []

        for kp in knowledge_analysis:
            if kp['rate'] < threshold:
                weak_points.append({
                    'name': kp['name'],
                    'score_rate': kp['rate'],
                    'suggestion': f"建议加强对「{kp['name']}」相关知识的学习"
                })

        return weak_points

    def _identify_strong_points(self, knowledge_analysis: List[Dict],
                                  threshold: float = 80.0) -> List[Dict]:
        """识别优势知识点（得分率高于阈值）"""
        strong_points = []

        for kp in knowledge_analysis:
            if kp['rate'] >= threshold:
                strong_points.append({
                    'name': kp['name'],
                    'score_rate': kp['rate']
                })

        return strong_points

    def _generate_ai_comment(self, report: ExamAnalysisReport) -> str:
        """生成AI评语"""
        # 基于得分率生成基础评语
        score_rate = report.score_rate

        if score_rate >= 90:
            level = "优秀"
            comment_base = "本次考试成绩优异，"
        elif score_rate >= 80:
            level = "良好"
            comment_base = "本次考试成绩良好，"
        elif score_rate >= 60:
            level = "及格"
            comment_base = "本次考试成绩及格，"
        else:
            level = "不及格"
            comment_base = "本次考试成绩不理想，"

        # 分析各题型表现
        type_comments = []
        for t, data in report.type_scores.items():
            if data['count'] > 0:
                type_name = {'choice': '选择题', 'blank': '填空题', 'short_answer': '简答题'}
                if data['rate'] >= 80:
                    type_comments.append(f"{type_name[t]}掌握较好（得分率{data['rate']}%）")
                elif data['rate'] < 60:
                    type_comments.append(f"{type_name[t]}需要加强（得分率{data['rate']}%）")

        # 构建完整评语
        comment_parts = [comment_base]

        if report.strong_points:
            strong_names = [p['name'] for p in report.strong_points[:3]]
            comment_parts.append(f"在「{'、'.join(strong_names)}」等知识点上表现出色。")

        if report.weak_points:
            weak_names = [p['name'] for p in report.weak_points[:3]]
            comment_parts.append(f"在「{'、'.join(weak_names)}」等知识点上存在不足，需要重点复习。")

        if type_comments:
            comment_parts.append("题型方面，" + "；".join(type_comments) + "。")

        # 如果有LLM，调用生成更详细的评语
        if self.llm_client:
            try:
                prompt = self._build_comment_prompt(report)
                # 这里可以调用LLM生成更个性化的评语
                # ai_comment = self.llm_client.generate(prompt)
                # return ai_comment
            except Exception as e:
                logger.error(f"AI评语生成失败: {e}")

        return "".join(comment_parts)

    def _build_comment_prompt(self, report: ExamAnalysisReport) -> str:
        """构建评语生成提示词"""
        return f"""
        请根据以下考试数据，生成一段个性化评语（100-200字）：

        总分：{report.total_score}/{report.max_score}（得分率{report.score_rate}%）

        各题型得分：
        - 选择题：{report.type_scores.get('choice', {}).get('score', 0)}/{report.type_scores.get('choice', {}).get('max', 0)}（{report.type_scores.get('choice', {}).get('rate', 0)}%）
        - 填空题：{report.type_scores.get('blank', {}).get('score', 0)}/{report.type_scores.get('blank', {}).get('max', 0)}（{report.type_scores.get('blank', {}).get('rate', 0)}%）
        - 简答题：{report.type_scores.get('short_answer', {}).get('score', 0)}/{report.type_scores.get('short_answer', {}).get('max', 0)}（{report.type_scores.get('short_answer', {}).get('rate', 0)}%）

        优势知识点：{', '.join([p['name'] for p in report.strong_points[:5]]) or '无'}
        薄弱知识点：{', '.join([p['name'] for p in report.weak_points[:5]]) or '无'}

        要求：
        1. 评语要有针对性，避免泛泛而谈
        2. 肯定优点，指出不足
        3. 给出具体的学习建议
        """

    def _generate_study_suggestions(self, weak_points: List[Dict],
                                     question_knowledge_map: Dict = None) -> List[Dict]:
        """生成学习建议"""
        suggestions = []

        for wp in weak_points:
            suggestion = {
                'point': wp['name'],
                'score_rate': wp['score_rate'],
                'document': None,
                'suggestion': wp.get('suggestion', f"建议加强对「{wp['name']}」的学习")
            }

            # 查找关联的制度文档
            if self.rag_module:
                try:
                    # 使用RAG搜索相关文档
                    # docs = self.rag_module.search(wp['name'], top_k=1)
                    # if docs:
                    #     suggestion['document'] = docs[0]['source']
                    pass
                except Exception as e:
                    logger.error(f"搜索关联文档失败: {e}")

            suggestions.append(suggestion)

        return suggestions

    def get_analysis_report(self, report_id: str) -> Optional[Dict]:
        """获取分析报告"""
        return self.db.get_analysis_report(report_id)

    def list_analysis_reports(self, exam_id: str = None,
                               limit: int = 20) -> List[Dict]:
        """获取分析报告列表"""
        return self.db.list_analysis_reports(exam_id, limit)


# ==================== 便捷函数 ====================

def create_services(db_path: str = "./data/exam_analysis.db",
                    rag_module=None, llm_client=None) -> Tuple[ExamAnalysisDB, QuestionMaintenanceService, ExamAnalysisService]:
    """
    创建服务实例

    Args:
        db_path: 数据库路径
        rag_module: RAG模块
        llm_client: LLM客户端

    Returns:
        (数据库实例, 题库维护服务, 整卷分析服务)
    """
    db = ExamAnalysisDB(db_path)
    maintenance_service = QuestionMaintenanceService(db, rag_module)
    analysis_service = ExamAnalysisService(db, rag_module, llm_client)

    return db, maintenance_service, analysis_service


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 测试数据库功能
    print("=" * 60)
    print("题库分析与维护服务测试")
    print("=" * 60)

    # 创建服务
    db, maintenance_svc, analysis_svc = create_services("./test_exam_analysis.db")

    # 测试知识点
    print("\n[1] 测试知识点管理...")
    kp_id = db.add_knowledge_point(KnowledgePoint(
        name="差旅报销流程",
        category="财务制度",
        description="员工差旅费用报销的相关规定和流程"
    ))
    print(f"  创建知识点: ID={kp_id}")

    kps = db.get_knowledge_points()
    print(f"  知识点列表: {len(kps)} 个")

    # 测试题目-制度关联
    print("\n[2] 测试题目-制度关联...")
    link_id = maintenance_svc.link_question_to_document(
        question_id="1",
        question_type="choice",
        exam_id="test-exam-001",
        document_id="public/差旅管理办法.txt",
        document_name="差旅管理办法",
        chapter="第三章 报销流程",
        key_points=["差旅报销流程", "报销标准"],
        relevance_score=0.9
    )
    print(f"  创建关联: ID={link_id}")

    links = db.get_question_documents("1", "choice")
    print(f"  题目关联的制度: {[l['document_name'] for l in links]}")

    # 测试题目-知识点关联
    print("\n[3] 测试题目-知识点关联...")
    qk_link_id = maintenance_svc.link_question_to_knowledge(
        question_id="1",
        question_type="choice",
        exam_id="test-exam-001",
        knowledge_point="差旅报销流程",
        weight=1.0
    )
    print(f"  创建关联: ID={qk_link_id}")

    # 测试制度变更处理
    print("\n[4] 测试制度变更处理...")
    result = maintenance_svc.on_document_change(
        document_id="public/差旅管理办法.txt",
        change_summary="更新了差旅报销标准，增加了高铁二等座报销规定"
    )
    print(f"  受影响题目: {len(result['affected_questions'])} 道")

    # 测试整卷分析
    print("\n[5] 测试整卷分析...")
    grade_report = {
        "exam_id": "test-exam-001",
        "exam_name": "差旅管理办法测试",
        "student_name": "测试学员",
        "total_score": 75,
        "max_score": 100,
        "score_rate": 75.0,
        "questions": [
            {"type": "choice", "id": "1", "score": 2, "max_score": 2, "correct": True},
            {"type": "choice", "id": "2", "score": 0, "max_score": 2, "correct": False},
            {"type": "blank", "id": "1", "score": 3, "max_score": 3, "correct": True},
            {"type": "blank", "id": "2", "score": 1.5, "max_score": 3, "correct": False},
            {"type": "short_answer", "id": "1", "score": 8, "max_score": 10, "correct": False}
        ]
    }

    question_knowledge_map = {
        "choice_1": [{"name": "差旅报销流程", "weight": 1.0}],
        "choice_2": [{"name": "报销标准", "weight": 1.0}],
        "blank_1": [{"name": "差旅报销流程", "weight": 1.0}],
        "blank_2": [{"name": "审批流程", "weight": 1.0}],
        "short_answer_1": [{"name": "差旅报销流程", "weight": 0.5}, {"name": "报销标准", "weight": 0.5}]
    }

    analysis_report = analysis_svc.analyze_exam_paper(grade_report, question_knowledge_map)
    print(f"  分析报告ID: {analysis_report.report_id}")
    print(f"  AI评语: {analysis_report.ai_comment[:100]}...")
    print(f"  薄弱知识点: {[wp['name'] for wp in analysis_report.weak_points]}")
    print(f"  优势知识点: {[sp['name'] for sp in analysis_report.strong_points]}")

    # 清理测试数据库
    import os
    if os.path.exists("./test_exam_analysis.db"):
        os.remove("./test_exam_analysis.db")
        print("\n[OK] 测试数据库已清理")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
