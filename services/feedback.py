"""
问答质量闭环服务

功能：
1. GKPT-AI-013 问答质量闭环
   - 用户点赞/踩反馈
   - 质量分析报告（周/月）
   - FAQ自动沉淀
"""

import json
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict, field
from collections import Counter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 数据类定义 ====================

@dataclass
class Feedback:
    """用户反馈"""
    id: Optional[int] = None
    session_id: str = ""
    query: str = ""
    answer: str = ""
    sources: List[str] = field(default_factory=list)
    rating: int = 0  # 1=赞, -1=踩
    reason: str = ""  # 点踩原因
    user_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class FAQ:
    """FAQ条目"""
    id: Optional[int] = None
    question: str = ""
    answer: str = ""
    source_documents: List[str] = field(default_factory=list)
    frequency: int = 0
    avg_rating: float = 0.0
    status: str = "draft"  # draft/approved/disabled
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class QualityReport:
    """质量报告"""
    id: Optional[int] = None
    report_type: str = "weekly"  # daily/weekly/monthly
    start_date: str = ""
    end_date: str = ""
    total_queries: int = 0
    total_feedback: int = 0
    positive_count: int = 0
    negative_count: int = 0
    avg_rating: float = 0.0
    satisfaction_rate: float = 0.0
    high_freq_queries: List[Dict] = field(default_factory=list)
    low_rating_queries: List[Dict] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "report_type": self.report_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_queries": self.total_queries,
            "total_feedback": self.total_feedback,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "avg_rating": self.avg_rating,
            "satisfaction_rate": self.satisfaction_rate,
            "high_freq_queries": self.high_freq_queries,
            "low_rating_queries": self.low_rating_queries,
            "improvement_suggestions": self.improvement_suggestions,
            "created_at": self.created_at
        }


# ==================== 数据库管理 ====================

class FeedbackDB:
    """反馈数据库"""

    def __init__(self, db_path: str = "./data/feedback.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 反馈记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                query TEXT NOT NULL,
                answer TEXT,
                sources TEXT,
                rating INTEGER NOT NULL,
                reason TEXT,
                user_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # FAQ表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                source_documents TEXT,
                frequency INTEGER DEFAULT 1,
                avg_rating REAL DEFAULT 0,
                status TEXT DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 质量报告表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quality_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                total_queries INTEGER DEFAULT 0,
                total_feedback INTEGER DEFAULT 0,
                positive_count INTEGER DEFAULT 0,
                negative_count INTEGER DEFAULT 0,
                avg_rating REAL DEFAULT 0,
                satisfaction_rate REAL DEFAULT 0,
                high_freq_queries TEXT,
                low_rating_queries TEXT,
                improvement_suggestions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # FAQ建议表（高频问题自动推荐）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faq_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                answer TEXT,
                frequency INTEGER DEFAULT 1,
                avg_rating REAL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedbacks(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedbacks(rating)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedbacks(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_faq_status ON faqs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_faq_suggestion_status ON faq_suggestions(status)")

        conn.commit()
        conn.close()

    # ==================== 反馈操作 ====================

    def add_feedback(self, feedback: Feedback) -> int:
        """添加反馈"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO feedbacks
            (session_id, query, answer, sources, rating, reason, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback.session_id,
            feedback.query,
            feedback.answer,
            json.dumps(feedback.sources, ensure_ascii=False),
            feedback.rating,
            feedback.reason,
            feedback.user_id,
            feedback.created_at
        ))

        feedback_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"添加反馈: session={feedback.session_id}, rating={feedback.rating}")
        return feedback_id

    def get_feedback(self, feedback_id: int) -> Optional[Dict]:
        """获取反馈详情"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM feedbacks WHERE id = ?", (feedback_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))
        if result.get('sources'):
            result['sources'] = json.loads(result['sources'])
        return result

    def get_feedbacks(self, rating: int = None, user_id: str = None,
                      start_date: str = None, end_date: str = None,
                      limit: int = 100) -> List[Dict]:
        """获取反馈列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        conditions = []
        params = []

        if rating is not None:
            conditions.append("rating = ?")
            params.append(rating)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if start_date:
            conditions.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("created_at <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor.execute(f"""
            SELECT * FROM feedbacks
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """, params)

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            if item.get('sources'):
                item['sources'] = json.loads(item['sources'])
            results.append(item)

        return results

    def get_feedback_stats(self, start_date: str = None, end_date: str = None) -> Dict:
        """获取反馈统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        conditions = []
        params = []

        if start_date:
            conditions.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("created_at <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 总数
        cursor.execute(f"SELECT COUNT(*) FROM feedbacks WHERE {where_clause}", params)
        total = cursor.fetchone()[0]

        # 正面/负面
        if conditions:
            cursor.execute(f"SELECT COUNT(*) FROM feedbacks WHERE {where_clause} AND rating = 1", params)
        else:
            cursor.execute("SELECT COUNT(*) FROM feedbacks WHERE rating = 1")
        positive = cursor.fetchone()[0]

        if conditions:
            cursor.execute(f"SELECT COUNT(*) FROM feedbacks WHERE {where_clause} AND rating = -1", params)
        else:
            cursor.execute("SELECT COUNT(*) FROM feedbacks WHERE rating = -1")
        negative = cursor.fetchone()[0]

        # 平均评分
        cursor.execute(f"SELECT AVG(rating) FROM feedbacks WHERE {where_clause}", params)
        avg_rating = cursor.fetchone()[0] or 0

        conn.close()

        satisfaction_rate = (positive / total * 100) if total > 0 else 0

        return {
            "total_feedback": total,
            "positive_count": positive,
            "negative_count": negative,
            "avg_rating": round(avg_rating, 2),
            "satisfaction_rate": round(satisfaction_rate, 1)
        }

    # ==================== FAQ操作 ====================

    def add_faq(self, faq: FAQ) -> int:
        """添加FAQ"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO faqs
            (question, answer, source_documents, frequency, avg_rating, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            faq.question,
            faq.answer,
            json.dumps(faq.source_documents, ensure_ascii=False),
            faq.frequency,
            faq.avg_rating,
            faq.status,
            faq.created_at,
            faq.updated_at
        ))

        faq_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"添加FAQ: {faq.question[:50]}...")
        return faq_id

    def get_faq(self, faq_id: int) -> Optional[Dict]:
        """获取FAQ详情"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM faqs WHERE id = ?", (faq_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))
        if result.get('source_documents'):
            result['source_documents'] = json.loads(result['source_documents'])
        return result

    def get_faqs(self, status: str = None, limit: int = 50) -> List[Dict]:
        """获取FAQ列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if status:
            cursor.execute("""
                SELECT * FROM faqs WHERE status = ?
                ORDER BY frequency DESC, avg_rating DESC
                LIMIT ?
            """, (status, limit))
        else:
            cursor.execute("""
                SELECT * FROM faqs
                ORDER BY frequency DESC, avg_rating DESC
                LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        results = []
        for row in rows:
            item = dict(zip(columns, row))
            if item.get('source_documents'):
                item['source_documents'] = json.loads(item['source_documents'])
            results.append(item)

        return results

    def update_faq(self, faq_id: int, updates: Dict) -> bool:
        """更新FAQ"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 构建更新语句
        set_clause = []
        params = []

        for key, value in updates.items():
            if key in ['question', 'answer', 'status', 'frequency', 'avg_rating']:
                set_clause.append(f"{key} = ?")
                params.append(value)
            elif key == 'source_documents':
                set_clause.append("source_documents = ?")
                params.append(json.dumps(value, ensure_ascii=False))

        if not set_clause:
            conn.close()
            return False

        set_clause.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(faq_id)

        cursor.execute(f"""
            UPDATE faqs SET {', '.join(set_clause)} WHERE id = ?
        """, params)

        affected = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return affected

    def delete_faq(self, faq_id: int) -> bool:
        """删除FAQ"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
        affected = cursor.rowcount > 0

        conn.commit()
        conn.close()

        return affected

    # ==================== FAQ建议操作 ====================

    def add_faq_suggestion(self, query: str, answer: str = "",
                           frequency: int = 1, avg_rating: float = 0) -> int:
        """添加FAQ建议"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 检查是否已存在相似问题
        cursor.execute("""
            SELECT id, frequency FROM faq_suggestions
            WHERE query = ? AND status = 'pending'
        """, (query,))

        existing = cursor.fetchone()
        if existing:
            # 更新频率
            cursor.execute("""
                UPDATE faq_suggestions
                SET frequency = ?, avg_rating = ?
                WHERE id = ?
            """, (existing[1] + frequency, avg_rating, existing[0]))
            conn.commit()
            conn.close()
            return existing[0]

        cursor.execute("""
            INSERT INTO faq_suggestions (query, answer, frequency, avg_rating, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (query, answer, frequency, avg_rating, datetime.now().isoformat()))

        suggestion_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return suggestion_id

    def get_faq_suggestions(self, status: str = "pending", limit: int = 50) -> List[Dict]:
        """获取FAQ建议列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM faq_suggestions
            WHERE status = ?
            ORDER BY frequency DESC, avg_rating DESC
            LIMIT ?
        """, (status, limit))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    def approve_faq_suggestion(self, suggestion_id: int) -> int:
        """批准FAQ建议，转为正式FAQ"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 获取建议内容
        cursor.execute("SELECT * FROM faq_suggestions WHERE id = ?", (suggestion_id,))
        suggestion = cursor.fetchone()

        if not suggestion:
            conn.close()
            return -1

        columns = [desc[0] for desc in cursor.description]
        suggestion_dict = dict(zip(columns, suggestion))

        # 创建FAQ
        cursor.execute("""
            INSERT INTO faqs (question, answer, frequency, avg_rating, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'approved', ?, ?)
        """, (
            suggestion_dict['query'],
            suggestion_dict['answer'],
            suggestion_dict['frequency'],
            suggestion_dict['avg_rating'],
            datetime.now().isoformat(),
            datetime.now().isoformat()
        ))

        faq_id = cursor.lastrowid

        # 更新建议状态
        cursor.execute("UPDATE faq_suggestions SET status = 'approved' WHERE id = ?", (suggestion_id,))

        conn.commit()
        conn.close()

        logger.info(f"批准FAQ建议: {suggestion_dict['query'][:50]}...")
        return faq_id

    def reject_faq_suggestion(self, suggestion_id: int) -> bool:
        """拒绝FAQ建议"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("UPDATE faq_suggestions SET status = 'rejected' WHERE id = ?", (suggestion_id,))
        affected = cursor.rowcount > 0

        conn.commit()
        conn.close()

        return affected

    # ==================== 报告操作 ====================

    def save_report(self, report: QualityReport) -> int:
        """保存报告"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO quality_reports
            (report_type, start_date, end_date, total_queries, total_feedback,
             positive_count, negative_count, avg_rating, satisfaction_rate,
             high_freq_queries, low_rating_queries, improvement_suggestions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report.report_type,
            report.start_date,
            report.end_date,
            report.total_queries,
            report.total_feedback,
            report.positive_count,
            report.negative_count,
            report.avg_rating,
            report.satisfaction_rate,
            json.dumps(report.high_freq_queries, ensure_ascii=False),
            json.dumps(report.low_rating_queries, ensure_ascii=False),
            json.dumps(report.improvement_suggestions, ensure_ascii=False),
            report.created_at
        ))

        report_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return report_id

    def get_report(self, report_id: int) -> Optional[Dict]:
        """获取报告详情"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM quality_reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))

        for field in ['high_freq_queries', 'low_rating_queries', 'improvement_suggestions']:
            if result.get(field):
                result[field] = json.loads(result[field])

        return result

    def get_latest_report(self, report_type: str = "weekly") -> Optional[Dict]:
        """获取最新报告"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM quality_reports
            WHERE report_type = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (report_type,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))

        for field in ['high_freq_queries', 'low_rating_queries', 'improvement_suggestions']:
            if result.get(field):
                result[field] = json.loads(result[field])

        return result


# ==================== 质量闭环服务 ====================

class FeedbackService:
    """问答质量闭环服务"""

    def __init__(self, db: FeedbackDB, faq_threshold: int = 5):
        self.db = db
        self.faq_threshold = faq_threshold  # 高频问题阈值
        self.llm_client = None
        self._init_llm()

    def _init_llm(self):
        """初始化LLM客户端（用于生成改进建议）"""
        try:
            from config import API_KEY, BASE_URL, MODEL
            from openai import OpenAI

            self.llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
            self.model = MODEL
            logger.info("LLM客户端初始化成功")
        except ImportError:
            logger.warning("未找到LLM配置，改进建议功能受限")
            self.llm_client = None

    def submit_feedback(self, session_id: str, query: str, answer: str,
                        rating: int, sources: List[str] = None,
                        reason: str = None, user_id: str = None) -> Dict:
        """
        提交反馈

        Args:
            session_id: 会话ID
            query: 用户问题
            answer: AI回答
            rating: 评分 (1=赞, -1=踩)
            sources: 来源文档
            reason: 点踩原因
            user_id: 用户ID

        Returns:
            反馈结果，包含是否触发FAQ建议
        """
        # 1. 存储反馈
        feedback = Feedback(
            session_id=session_id,
            query=query,
            answer=answer,
            sources=sources or [],
            rating=rating,
            reason=reason or "",
            user_id=user_id or ""
        )

        feedback_id = self.db.add_feedback(feedback)

        result = {
            "feedback_id": feedback_id,
            "rating": rating,
            "faq_suggested": False
        }

        # 2. 检查是否需要沉淀为FAQ
        if rating > 0:  # 正面反馈
            # 检查相似问题
            similar_faqs = self._find_similar_faqs(query)

            if similar_faqs:
                # 更新已有FAQ频率
                self.db.update_faq(similar_faqs[0]['id'], {
                    'frequency': similar_faqs[0]['frequency'] + 1
                })
            else:
                # 检查是否高频问题
                query_count = self._count_similar_queries(query)
                if query_count >= self.faq_threshold:
                    # 自动推荐为FAQ
                    suggestion_id = self.db.add_faq_suggestion(
                        query=query,
                        answer=answer,
                        frequency=query_count,
                        avg_rating=1.0
                    )
                    result['faq_suggested'] = True
                    result['suggestion_id'] = suggestion_id
                    logger.info(f"高频问题推荐FAQ: {query[:50]}... (出现{query_count}次)")

        return result

    def _find_similar_faqs(self, query: str) -> List[Dict]:
        """查找相似FAQ"""
        # 简单实现：查找包含关键词的FAQ
        # TODO: 可以使用向量相似度
        faqs = self.db.get_faqs(status="approved", limit=100)

        similar = []
        query_lower = query.lower()

        for faq in faqs:
            # 检查问题相似度
            if query_lower in faq['question'].lower() or faq['question'].lower() in query_lower:
                similar.append(faq)

        return similar[:3]

    def _count_similar_queries(self, query: str) -> int:
        """统计相似问题出现次数"""
        feedbacks = self.db.get_feedbacks(limit=1000)

        query_lower = query.lower()
        count = 0

        # 使用 Counter 统计相似问题
        queries = [f['query'].lower() for f in feedbacks]

        # 简单匹配：包含关键词
        for q in queries:
            if query_lower in q or q in query_lower:
                count += 1

        return count

    def get_high_freq_queries(self, start_date: str = None, end_date: str = None,
                               top_n: int = 20) -> List[Dict]:
        """获取高频问题"""
        feedbacks = self.db.get_feedbacks(start_date=start_date, end_date=end_date, limit=10000)

        # 统计问题频率
        query_counter = Counter()
        query_answers = {}

        for f in feedbacks:
            query = f['query']
            query_counter[query] += 1
            if query not in query_answers:
                query_answers[query] = f['answer']

        # 排序
        top_queries = query_counter.most_common(top_n)

        return [
            {
                "query": query,
                "frequency": freq,
                "sample_answer": query_answers.get(query, "")[:200]
            }
            for query, freq in top_queries
        ]

    def get_low_rating_queries(self, start_date: str = None, end_date: str = None,
                                threshold: float = 0, limit: int = 20) -> List[Dict]:
        """获取低分问题"""
        feedbacks = self.db.get_feedbacks(rating=-1, start_date=start_date,
                                           end_date=end_date, limit=limit)

        return [
            {
                "query": f['query'],
                "answer": f['answer'][:200] if f.get('answer') else "",
                "reason": f.get('reason', ""),
                "created_at": f['created_at']
            }
            for f in feedbacks
        ]

    def generate_report(self, report_type: str = "weekly",
                        start_date: str = None, end_date: str = None) -> QualityReport:
        """
        生成质量报告

        Args:
            report_type: 报告类型 (daily/weekly/monthly)
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            QualityReport
        """
        # 计算日期范围
        if not start_date or not end_date:
            today = datetime.now()
            if report_type == "daily":
                start_date = today.strftime("%Y-%m-%d")
                end_date = start_date
            elif report_type == "weekly":
                week_start = today - timedelta(days=today.weekday())
                week_end = week_start + timedelta(days=6)
                start_date = week_start.strftime("%Y-%m-%d")
                end_date = week_end.strftime("%Y-%m-%d")
            elif report_type == "monthly":
                month_start = today.replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                start_date = month_start.strftime("%Y-%m-%d")
                end_date = month_end.strftime("%Y-%m-%d")

        # 获取统计数据
        stats = self.db.get_feedback_stats(
            start_date=f"{start_date}T00:00:00",
            end_date=f"{end_date}T23:59:59"
        )

        high_freq = self.get_high_freq_queries(
            start_date=f"{start_date}T00:00:00",
            end_date=f"{end_date}T23:59:59"
        )

        low_rating = self.get_low_rating_queries(
            start_date=f"{start_date}T00:00:00",
            end_date=f"{end_date}T23:59:59"
        )

        # 生成改进建议
        suggestions = self._generate_suggestions(stats, low_rating)

        report = QualityReport(
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            total_queries=stats['total_feedback'],  # 使用反馈数作为查询数近似
            total_feedback=stats['total_feedback'],
            positive_count=stats['positive_count'],
            negative_count=stats['negative_count'],
            avg_rating=stats['avg_rating'],
            satisfaction_rate=stats['satisfaction_rate'],
            high_freq_queries=high_freq,
            low_rating_queries=low_rating,
            improvement_suggestions=suggestions
        )

        # 保存报告
        self.db.save_report(report)

        return report

    def _generate_suggestions(self, stats: Dict, low_rating: List[Dict]) -> List[str]:
        """生成改进建议"""
        suggestions = []

        # 基于统计数据
        if stats['satisfaction_rate'] < 70:
            suggestions.append(f"满意度较低({stats['satisfaction_rate']}%)，建议检查知识库覆盖度")

        if stats['negative_count'] > stats['positive_count']:
            suggestions.append("负面反馈较多，建议分析低分问题并改进答案质量")

        # 基于低分问题
        if len(low_rating) > 5:
            suggestions.append(f"存在{len(low_rating)}个低分问题，建议针对性优化")

        # 使用LLM生成更具体的建议
        if self.llm_client and low_rating:
            try:
                low_rating_text = "\n".join([
                    f"- {q['query']}: {q.get('reason', '无原因')}"
                    for q in low_rating[:5]
                ])

                prompt = f"""基于以下低分问题和原因，给出3-5条改进建议：

{low_rating_text}

请直接输出建议，每条一行，不要编号。"""

                response = self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=500
                )

                llm_suggestions = response.choices[0].message.content.strip().split("\n")
                suggestions.extend([s.strip() for s in llm_suggestions if s.strip()])

            except Exception as e:
                logger.error(f"LLM生成建议失败: {e}")

        if not suggestions:
            suggestions.append("继续保持当前服务质量")

        return suggestions


# ==================== 便捷函数 ====================

def create_feedback_service(db_path: str = "./data/feedback.db",
                             faq_threshold: int = 5) -> Tuple[FeedbackDB, FeedbackService]:
    """
    创建反馈服务实例

    Args:
        db_path: 数据库路径
        faq_threshold: FAQ高频阈值

    Returns:
        (数据库实例, 反馈服务实例)
    """
    db = FeedbackDB(db_path)
    service = FeedbackService(db, faq_threshold)
    return db, service


# ==================== 使用示例 ====================

if __name__ == "__main__":
    import sys

    # 设置编码
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("问答质量闭环服务测试")
    print("=" * 60)

    # 创建服务
    db, service = create_feedback_service(db_path="./test_feedback.db")

    # 测试反馈
    print("\n[1] 测试反馈提交...")
    result1 = service.submit_feedback(
        session_id="session_001",
        query="差旅报销流程是什么？",
        answer="差旅报销流程包括：1.填写报销单 2.部门审批 3.财务审核 4.打款",
        rating=1,
        sources=["public/差旅管理办法.txt"]
    )
    print(f"  反馈ID: {result1['feedback_id']}, 评分: {result1['rating']}")

    # 提交多次相似问题以触发FAQ建议
    for i in range(5):
        service.submit_feedback(
            session_id=f"session_{i+2}",
            query="如何申请差旅报销？",
            answer="请填写差旅报销单，经部门审批后提交财务。",
            rating=1
        )
    print(f"  提交5次相似问题")

    # 检查FAQ建议
    suggestions = db.get_faq_suggestions()
    print(f"  FAQ建议数: {len(suggestions)}")
    for s in suggestions[:3]:
        print(f"    - {s['query'][:30]}... (频率: {s['frequency']})")

    # 测试负面反馈
    print("\n[2] 测试负面反馈...")
    result2 = service.submit_feedback(
        session_id="session_neg",
        query="这个回答不准确",
        answer="抱歉，请提供更具体的问题",
        rating=-1,
        reason="回答与问题不符"
    )
    print(f"  反馈ID: {result2['feedback_id']}, 评分: {result2['rating']}")

    # 测试统计
    print("\n[3] 测试反馈统计...")
    stats = db.get_feedback_stats()
    print(f"  总反馈: {stats['total_feedback']}")
    print(f"  正面: {stats['positive_count']}, 负面: {stats['negative_count']}")
    print(f"  满意度: {stats['satisfaction_rate']}%")

    # 测试报告生成
    print("\n[4] 测试报告生成...")
    report = service.generate_report("weekly")
    print(f"  报告类型: {report.report_type}")
    print(f"  时间范围: {report.start_date} ~ {report.end_date}")
    print(f"  高频问题: {len(report.high_freq_queries)} 个")
    print(f"  低分问题: {len(report.low_rating_queries)} 个")
    print(f"  改进建议: {report.improvement_suggestions[:2]}")

    # 测试FAQ管理
    print("\n[5] 测试FAQ管理...")
    if suggestions:
        # 批准第一个建议
        faq_id = db.approve_faq_suggestion(suggestions[0]['id'])
        print(f"  批准FAQ建议: ID={faq_id}")

        # 获取FAQ列表
        faqs = db.get_faqs(status="approved")
        print(f"  已批准FAQ: {len(faqs)} 个")

    # 清理测试数据库
    import os
    for f in ["./test_feedback.db", "./test_feedback.db-wal", "./test_feedback.db-shm"]:
        if os.path.exists(f):
            os.remove(f)
            print(f"\n  [OK] 清理: {f}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
