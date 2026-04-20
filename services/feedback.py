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
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict, field
from collections import Counter

from data.db import get_connection, init_databases

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

    def __init__(self):
        init_databases()

    def _init_db(self):
        """初始化数据库表 - 已由 init_databases() 统一处理"""
        pass

    # ==================== 反馈操作 ====================

    def add_feedback(self, feedback: Feedback) -> int:
        """添加反馈"""
        with get_connection("core") as conn:
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

        logger.info(f"添加反馈: session={feedback.session_id}, rating={feedback.rating}")
        return feedback_id

    def get_feedback(self, feedback_id: int) -> Optional[Dict]:
        """获取反馈详情"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM feedbacks WHERE id = ?", (feedback_id,))
            row = cursor.fetchone()

        if not row:
            return None

        # sqlite3.Row 支持直接转换为字典
        result = dict(row)
        if result.get('sources'):
            result['sources'] = json.loads(result['sources'])
        return result

    def get_feedbacks(self, rating: int = None, user_id: str = None,
                      start_date: str = None, end_date: str = None,
                      limit: int = 100) -> List[Dict]:
        """获取反馈列表"""
        with get_connection("core") as conn:
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

        results = []
        for row in rows:
            # sqlite3.Row 支持直接转换为字典
            item = dict(row)
            if item.get('sources'):
                item['sources'] = json.loads(item['sources'])
            results.append(item)

        return results

    def get_feedback_stats(self, start_date: str = None, end_date: str = None) -> Dict:
        """获取反馈统计"""
        with get_connection("core") as conn:
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
        with get_connection("core") as conn:
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

        logger.info(f"添加FAQ: {faq.question[:50]}...")
        return faq_id

    def get_faq(self, faq_id: int) -> Optional[Dict]:
        """获取FAQ详情"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM faqs WHERE id = ?", (faq_id,))
            row = cursor.fetchone()

        if not row:
            return None

        # sqlite3.Row 支持直接转换为字典
        result = dict(row)
        if result.get('source_documents'):
            result['source_documents'] = json.loads(result['source_documents'])
        return result

    def get_faqs(self, status: str = None, limit: int = 50) -> List[Dict]:
        """获取FAQ列表"""
        with get_connection("core") as conn:
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

        results = []
        for row in rows:
            # sqlite3.Row 支持直接转换为字典
            item = dict(row)
            if item.get('source_documents'):
                item['source_documents'] = json.loads(item['source_documents'])
            results.append(item)

        return results

    def update_faq(self, faq_id: int, updates: Dict) -> bool:
        """更新FAQ"""
        with get_connection("core") as conn:
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
                return False

            set_clause.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(faq_id)

            cursor.execute(f"""
                UPDATE faqs SET {', '.join(set_clause)} WHERE id = ?
            """, params)

            affected = cursor.rowcount > 0

        return affected

    def delete_faq(self, faq_id: int) -> bool:
        """删除FAQ"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
            affected = cursor.rowcount > 0

        return affected

    # ==================== FAQ建议操作 ====================

    def add_faq_suggestion(self, query: str, answer: str = "",
                           frequency: int = 1, avg_rating: float = 0) -> int:
        """添加FAQ建议"""
        with get_connection("core") as conn:
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
                """, (existing['frequency'] + frequency, avg_rating, existing['id']))
                return existing['id']

            cursor.execute("""
                INSERT INTO faq_suggestions (query, answer, frequency, avg_rating, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
            """, (query, answer, frequency, avg_rating, datetime.now().isoformat()))

            suggestion_id = cursor.lastrowid

        return suggestion_id

    def get_faq_suggestions(self, status: str = "pending", limit: int = 50) -> List[Dict]:
        """获取FAQ建议列表"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM faq_suggestions
                WHERE status = ?
                ORDER BY frequency DESC, avg_rating DESC
                LIMIT ?
            """, (status, limit))

            rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def approve_faq_suggestion(self, suggestion_id: int) -> int:
        """批准FAQ建议，转为正式FAQ"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            # 获取建议内容
            cursor.execute("SELECT * FROM faq_suggestions WHERE id = ?", (suggestion_id,))
            suggestion = cursor.fetchone()

            if not suggestion:
                return -1

            # sqlite3.Row 支持直接通过列名访问
            suggestion_dict = dict(suggestion)

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

        logger.info(f"批准FAQ建议: {suggestion_dict['query'][:50]}...")
        return faq_id

    def reject_faq_suggestion(self, suggestion_id: int) -> bool:
        """拒绝FAQ建议"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("UPDATE faq_suggestions SET status = 'rejected' WHERE id = ?", (suggestion_id,))
            affected = cursor.rowcount > 0

        return affected

    # ==================== 报告操作 ====================

    def save_report(self, report: QualityReport) -> int:
        """保存报告"""
        with get_connection("core") as conn:
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

        return report_id

    def get_report(self, report_id: int) -> Optional[Dict]:
        """获取报告详情"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM quality_reports WHERE id = ?", (report_id,))
            row = cursor.fetchone()

        if not row:
            return None

        # sqlite3.Row 支持直接转换为字典
        result = dict(row)

        for field in ['high_freq_queries', 'low_rating_queries', 'improvement_suggestions']:
            if result.get(field):
                result[field] = json.loads(result[field])

        return result

    def get_latest_report(self, report_type: str = "weekly") -> Optional[Dict]:
        """获取最新报告"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM quality_reports
                WHERE report_type = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (report_type,))

            row = cursor.fetchone()

        if not row:
            return None

        # sqlite3.Row 支持直接转换为字典
        result = dict(row)

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

    # ==================== FAQ 问题扩写（Multi-Query Indexing）====================

    def _expand_faq_questions(self, question: str) -> List[str]:
        """
        用 LLM 扩写 FAQ 问题为 3 种不同问法

        Args:
            question: 原问题

        Returns:
            扩写后的问题列表（最多3个）
        """
        if not self.llm_client:
            logger.warning("LLM客户端未初始化，跳过问题扩写")
            return []

        try:
            prompt = f"""请将以下问题改写为3种不同的表达方式，保持语义不变：
原问题：{question}

要求：
1. 使用不同的词汇和句式
2. 保持简洁（不超过20字）
3. 覆盖用户可能的不同问法

直接输出3个改写，每行一个。"""

            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=200
            )

            variants = response.choices[0].message.content.strip().split('\n')
            # 清理并过滤空行
            variants = [v.strip().lstrip('0123456789.-、') for v in variants if v.strip()]

            logger.info(f"问题扩写成功: {question[:30]}... -> {len(variants)} 个变体")
            return variants[:3]  # 最多返回3个

        except Exception as e:
            logger.error(f"问题扩写失败: {e}")
            return []

    # ==================== FAQ 同步到知识库 ====================

    def _sync_faq_to_knowledge_base(self, faq_id: int, question: str, answer: str) -> bool:
        """
        将 FAQ 同步到知识库（问题分离存储）

        核心策略：
        1. 扩写问题为多个变体
        2. 每个问题单独向量化
        3. 答案存在 metadata 中

        Args:
            faq_id: FAQ ID
            question: 问题
            answer: 答案

        Returns:
            是否同步成功
        """
        try:
            from core.engine import RAGEngine

            # 获取引擎
            engine = RAGEngine.get_instance()
            if not engine._initialized:
                engine.initialize()

            # 获取或创建独立的 FAQ 集合（与普通文档分离）
            if engine.kb_manager:
                # 多向量库模式：使用专门的 faq_kb 集合
                # get_collection 内部已实现 get_or_create 逻辑
                faq_collection = engine.kb_manager.get_collection('faq_kb')
            else:
                # 单向量库模式：创建独立的 faq 集合
                faq_collection = engine.chroma_client.get_or_create_collection(
                    name="faq_collection",
                    metadata={"description": "FAQ 专属向量库，独立于普通文档"}
                )

            if not faq_collection:
                logger.error("无法获取 FAQ 向量库")
                return False

            # 1. 扩写问题
            variants = self._expand_faq_questions(question)
            all_questions = [question] + variants  # 原问题 + 变体

            # 2. 为每个问题生成向量
            embeddings = engine.embedding_model.encode(all_questions).tolist()

            # 3. 准备元数据
            now = datetime.now().isoformat()
            ids = []
            metas = []

            for i, q in enumerate(all_questions):
                chunk_id = f"faq_{faq_id}_v{i}"
                ids.append(chunk_id)
                metas.append({
                    "source": f"faq_{faq_id}",
                    "chunk_type": "faq",
                    "faq_answer": answer,
                    "is_variant": i > 0,
                    "created_at": now
                })

            # 4. 写入独立的 FAQ 向量库
            faq_collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=all_questions,
                metadatas=metas
            )

            # 5. 记录变体到数据库
            with get_connection("core") as conn:
                cursor = conn.cursor()
                for i, variant in enumerate(variants):
                    cursor.execute("""
                        INSERT INTO faq_variants (faq_id, variant_question, created_at)
                        VALUES (?, ?, ?)
                    """, (faq_id, variant, now))

            logger.info(f"FAQ同步成功: ID={faq_id}, 向量数={len(ids)}, 存储位置: faq_collection")
            return True

        except Exception as e:
            logger.error(f"FAQ同步失败: {e}")
            return False

    def _delete_faq_vectors(self, faq_id: int) -> bool:
        """
        删除 FAQ 在向量库中的所有向量

        由于 FAQ 存储在独立的集合中，可以精确删除而不影响其他数据

        Args:
            faq_id: FAQ ID

        Returns:
            是否删除成功
        """
        try:
            from core.engine import RAGEngine

            # 获取引擎
            engine = RAGEngine.get_instance()
            if not engine._initialized:
                engine.initialize()

            # 获取 FAQ 集合
            if engine.kb_manager:
                faq_collection = engine.kb_manager.get_collection('faq_kb')
            else:
                faq_collection = engine.chroma_client.get_or_create_collection(
                    name="faq_collection",
                    metadata={"description": "FAQ 专属向量库"}
                )

            if not faq_collection:
                logger.warning(f"FAQ 集合不存在，无需删除")
                return True

            # 获取该 FAQ 的所有向量 ID
            # 格式：faq_{faq_id}_v{i}
            all_ids = faq_collection.get()['ids']
            faq_ids = [id for id in all_ids if id.startswith(f"faq_{faq_id}_")]

            if faq_ids:
                faq_collection.delete(ids=faq_ids)
                logger.info(f"删除 FAQ 向量: ID={faq_id}, 向量数={len(faq_ids)}")

            # 同时删除数据库中的变体记录
            with get_connection("core") as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM faq_variants WHERE faq_id = ?", (faq_id,))

            return True

        except Exception as e:
            logger.error(f"删除 FAQ 向量失败: {e}")
            return False

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

                # 计算复合分数（频率 + 评分）
                faq_score = self._calculate_faq_score(query_count, 1.0)

                # 使用复合分数判断（> 0.5 才推荐）
                if faq_score > 0.5:
                    # 自动推荐为FAQ
                    suggestion_id = self.db.add_faq_suggestion(
                        query=query,
                        answer=answer,
                        frequency=query_count,
                        avg_rating=1.0
                    )
                    result['faq_suggested'] = True
                    result['suggestion_id'] = suggestion_id
                    result['faq_score'] = round(faq_score, 2)
                    logger.info(f"推荐FAQ: {query[:50]}... (频率={query_count}, 分数={faq_score:.2f})")

        return result

    def approve_and_sync_faq(self, suggestion_id: int) -> Dict:
        """
        批准FAQ建议并同步到知识库

        Args:
            suggestion_id: FAQ建议ID

        Returns:
            处理结果，包含faq_id和sync_status
        """
        # 1. 批准FAQ建议（数据库操作）
        faq_id = self.db.approve_faq_suggestion(suggestion_id)

        if faq_id <= 0:
            return {
                "success": False,
                "error": "FAQ建议不存在或已处理",
                "faq_id": -1
            }

        # 2. 获取FAQ详情
        faq = self.db.get_faq(faq_id)
        if not faq:
            return {
                "success": False,
                "error": "FAQ创建失败",
                "faq_id": faq_id
            }

        # 3. 同步到知识库
        sync_success = self._sync_faq_to_knowledge_base(
            faq_id=faq_id,
            question=faq['question'],
            answer=faq['answer']
        )

        return {
            "success": True,
            "faq_id": faq_id,
            "question": faq['question'],
            "sync_status": "synced" if sync_success else "sync_failed"
        }

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

    def _calculate_faq_score(self, frequency: int, avg_rating: float) -> float:
        """
        计算 FAQ 推荐复合分数

        复合分数 = 频率分(40%) + 评分分(60%)

        Args:
            frequency: 问题出现频率
            avg_rating: 平均评分 (-1 到 1)

        Returns:
            复合分数 (0 到 1)
        """
        # 频率归一化（0-1），上限 20 次
        freq_score = min(1.0, frequency / 20)

        # 评分归一化（-1 到 1 映射到 0 到 1）
        rating_score = (avg_rating + 1) / 2

        # 复合分数
        return freq_score * 0.4 + rating_score * 0.6

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

    # ==================== 负反馈降权机制 ====================

    def get_low_rated_sources(self, min_count: int = 3) -> List[Dict]:
        """
        获取高频点踩的来源黑名单

        Args:
            min_count: 最小点踩次数阈值

        Returns:
            黑名单来源列表，包含 source 和点踩次数
        """
        with get_connection("core") as conn:
            cursor = conn.cursor()

            # 统计每个来源的负反馈次数
            cursor.execute("""
                SELECT sources, COUNT(*) as cnt
                FROM feedbacks
                WHERE rating = -1 AND sources IS NOT NULL
                GROUP BY sources
                HAVING cnt >= ?
                ORDER BY cnt DESC
            """, (min_count,))

            rows = cursor.fetchall()

        results = []
        for row in rows:
            sources_json = row['sources']
            if sources_json:
                try:
                    sources_list = json.loads(sources_json)
                    for source in sources_list:
                        results.append({
                            "source": source,
                            "dislike_count": row['cnt']
                        })
                except (json.JSONDecodeError, TypeError):
                    pass

        return results

    def get_chunk_blacklist(self, min_dislikes: int = 3) -> set:
        """
        获取 Chunk 黑名单（用于检索时过滤）

        Args:
            min_dislikes: 最小点踩次数阈值

        Returns:
            黑名单 source 集合
        """
        blacklisted = self.get_low_rated_sources(min_dislikes)
        return {item['source'] for item in blacklisted}

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

def create_feedback_service(faq_threshold: int = 5) -> Tuple[FeedbackDB, FeedbackService]:
    """
    创建反馈服务实例

    Args:
        faq_threshold: FAQ高频阈值

    Returns:
        (数据库实例, 反馈服务实例)
    """
    db = FeedbackDB()
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
    db, service = create_feedback_service()

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

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
