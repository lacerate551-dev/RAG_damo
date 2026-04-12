"""
题库维护钩子 - 知识库变更时自动触发

功能：
1. 变更监听 - 监听知识库文档变更事件
2. 影响分析 - 分析变更对题目的影响
3. 自动标记 - 标记受影响的题目
4. 建议生成 - 生成新题建议

使用方式：
    from question_maintenance_hook import on_knowledge_base_change

    # 触发钩子
    result = on_knowledge_base_change(
        collection="dept_finance",
        document_id="报销制度.pdf",
        change_type="DEPRECATED",
        change_details={"reason": "制度已更新"}
    )
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 数据类 ====================

@dataclass
class QuestionImpact:
    """题目影响分析结果"""
    question_id: str
    question_type: str          # choice/blank/short_answer
    exam_id: str
    impact_level: str           # high/medium/low
    suggested_action: str       # review/update_answer/disable
    reason: str
    affected_content: str       # 受影响的内容片段


# ==================== 核心钩子函数 ====================

def on_knowledge_base_change(
    collection: str,
    document_id: str,
    change_type: str,
    change_details: Dict = None
) -> Dict:
    """
    知识库变更钩子

    当文档被废止、修改或删除时触发，
    自动分析影响并标记相关题目。

    Args:
        collection: 向量库名称
        document_id: 文档ID（文件名）
        change_type: 变更类型
            - DEPRECATED: 文档已废止
            - MODIFIED: 文档已修改
            - DELETED: 文档已删除
            - ADDED: 新增文档
        change_details: 变更详情
            - reason: 变更原因
            - change_summary: 变更摘要
            - changed_sections: 变更的章节

    Returns:
        {
            "success": True,
            "affected_questions": [...],
            "suggestions": [...],
            "notifications_sent": 3
        }
    """
    logger.info(
        f"触发题库维护钩子: collection={collection}, "
        f"document={document_id}, change_type={change_type}"
    )

    change_details = change_details or {}
    affected_questions = []
    suggestions = []

    try:
        from exam_analysis import ExamAnalysisDB

        exam_db = ExamAnalysisDB("./data/exam_analysis.db")

        # 1. 查找关联的题目
        related_questions = _get_document_questions(exam_db, document_id)

        if not related_questions:
            logger.info(f"文档 {document_id} 没有关联的题目")
            return {
                "success": True,
                "affected_questions": [],
                "suggestions": [],
                "message": "没有关联的题目"
            }

        # 2. 根据变更类型处理
        if change_type == "DEPRECATED" or change_type == "DELETED":
            # 文档废止/删除 - 所有相关题目标记为需要审核
            affected_questions = _handle_deprecated(
                exam_db, document_id, related_questions, change_details
            )

        elif change_type == "MODIFIED":
            # 文档修改 - 分析影响级别
            affected_questions = _handle_modified(
                exam_db, document_id, related_questions, change_details
            )

            # 生成新题建议
            suggestions = _generate_question_suggestions(
                document_id, change_details
            )

        # 3. 发送通知
        notifications_sent = _send_notifications(
            document_id, affected_questions, change_type
        )

        logger.info(
            f"题库维护完成: affected={len(affected_questions)}, "
            f"suggestions={len(suggestions)}, notifications={notifications_sent}"
        )

        return {
            "success": True,
            "affected_questions": [_format_question(q) for q in affected_questions],
            "suggestions": suggestions,
            "notifications_sent": notifications_sent
        }

    except ImportError:
        logger.warning("exam_analysis 模块未安装，跳过题库维护")
        return {
            "success": False,
            "error": "exam_analysis 模块未安装",
            "affected_questions": [],
            "suggestions": []
        }
    except Exception as e:
        logger.error(f"题库维护钩子执行失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_questions": [],
            "suggestions": []
        }


# ==================== 内部处理函数 ====================

def _get_document_questions(exam_db, document_id: str) -> List[Dict]:
    """
    获取文档关联的题目

    Args:
        exam_db: 题库分析数据库实例
        document_id: 文档ID

    Returns:
        题目列表
    """
    try:
        questions = exam_db.get_document_questions(document_id)
        return questions or []
    except Exception as e:
        logger.warning(f"获取关联题目失败: {e}")
        return []


def _handle_deprecated(
    exam_db,
    document_id: str,
    questions: List[Dict],
    change_details: Dict
) -> List[Dict]:
    """
    处理文档废止

    所有关联题目标记为 affected，建议审核

    Args:
        exam_db: 数据库实例
        document_id: 文档ID
        questions: 关联题目列表
        change_details: 变更详情

    Returns:
        受影响的题目列表
    """
    affected = []
    reason = change_details.get("reason", "文档已废止")

    for q in questions:
        try:
            # 更新题目状态
            _update_question_status(
                exam_db,
                question_id=q.get("question_id"),
                question_type=q.get("question_type"),
                exam_id=q.get("exam_id"),
                status="affected",
                affected_by=document_id,
                suggested_action="review",
                reason=f"来源文档已废止: {reason}"
            )

            affected.append({
                "question_id": q.get("question_id"),
                "question_type": q.get("question_type"),
                "exam_id": q.get("exam_id"),
                "impact_level": "high",
                "suggested_action": "review",
                "reason": f"来源文档已废止: {reason}"
            })

        except Exception as e:
            logger.warning(f"更新题目状态失败: {q.get('question_id')}, {e}")

    return affected


def _handle_modified(
    exam_db,
    document_id: str,
    questions: List[Dict],
    change_details: Dict
) -> List[Dict]:
    """
    处理文档修改

    根据变更程度决定影响级别

    Args:
        exam_db: 数据库实例
        document_id: 文档ID
        questions: 关联题目列表
        change_details: 变更详情

    Returns:
        受影响的题目列表
    """
    affected = []

    # 分析变更影响
    impact_level = _analyze_change_impact(change_details)

    for q in questions:
        # 检查题目是否涉及变更的内容
        question_impact = _analyze_question_impact(q, change_details, impact_level)

        if question_impact["impact_level"] != "none":
            try:
                _update_question_status(
                    exam_db,
                    question_id=q.get("question_id"),
                    question_type=q.get("question_type"),
                    exam_id=q.get("exam_id"),
                    status="affected",
                    affected_by=document_id,
                    suggested_action=question_impact["suggested_action"],
                    reason=question_impact["reason"]
                )

                affected.append({
                    "question_id": q.get("question_id"),
                    "question_type": q.get("question_type"),
                    "exam_id": q.get("exam_id"),
                    "impact_level": question_impact["impact_level"],
                    "suggested_action": question_impact["suggested_action"],
                    "reason": question_impact["reason"]
                })

            except Exception as e:
                logger.warning(f"更新题目状态失败: {q.get('question_id')}, {e}")

    return affected


def _analyze_change_impact(change_details: Dict) -> str:
    """
    分析变更的整体影响级别

    Args:
        change_details: 变更详情

    Returns:
        影响级别: high/medium/low
    """
    # 检查是否有章节变更信息
    changed_sections = change_details.get("changed_sections", [])

    if len(changed_sections) > 5:
        return "high"
    elif len(changed_sections) > 2:
        return "medium"
    elif len(changed_sections) > 0:
        return "low"

    # 检查变更摘要关键词
    summary = change_details.get("change_summary", "").lower()

    high_keywords = ["删除", "废止", "取消", "重大变更", "金额", "日期", "规则"]
    medium_keywords = ["修改", "调整", "更新", "变更"]

    for kw in high_keywords:
        if kw in summary:
            return "high"

    for kw in medium_keywords:
        if kw in summary:
            return "medium"

    return "low"


def _analyze_question_impact(
    question: Dict,
    change_details: Dict,
    overall_impact: str
) -> Dict:
    """
    分析单个题目受影响的程度

    Args:
        question: 题目信息
        change_details: 变更详情
        overall_impact: 整体影响级别

    Returns:
        {
            "impact_level": "high/medium/low/none",
            "suggested_action": "review/update_answer/disable",
            "reason": "原因说明"
        }
    """
    # 检查题目关联的章节是否在变更范围内
    changed_sections = set(change_details.get("changed_sections", []))
    question_sections = set(question.get("sections", []) or question.get("chapters", []))

    # 如果题目关联的章节有变更
    affected_sections = changed_sections & question_sections

    if affected_sections:
        return {
            "impact_level": "high",
            "suggested_action": "review",
            "reason": f"题目涉及已变更的章节: {', '.join(affected_sections)}"
        }

    # 根据整体影响级别推断
    if overall_impact == "high":
        return {
            "impact_level": "medium",
            "suggested_action": "review",
            "reason": "文档有重大变更，建议检查题目有效性"
        }
    elif overall_impact == "medium":
        return {
            "impact_level": "low",
            "suggested_action": "update_answer",
            "reason": "文档有修改，可能需要更新答案"
        }

    return {
        "impact_level": "none",
        "suggested_action": "",
        "reason": ""
    }


def _update_question_status(
    exam_db,
    question_id: str,
    question_type: str,
    exam_id: str,
    status: str,
    affected_by: str,
    suggested_action: str,
    reason: str
):
    """
    更新题目状态

    Args:
        exam_db: 数据库实例
        question_id: 题目ID
        question_type: 题目类型
        exam_id: 试卷ID
        status: 新状态
        affected_by: 影响来源（文档ID）
        suggested_action: 建议操作
        reason: 原因
    """
    try:
        # 尝试使用 exam_analysis 的更新方法
        from exam_analysis import QuestionStatus

        exam_db.update_question_status(
            question_id=question_id,
            question_type=question_type,
            exam_id=exam_id,
            status=status,
            affected_by=affected_by,
            suggested_action=suggested_action
        )

        logger.info(f"更新题目状态: {question_id} -> {status}")

    except AttributeError:
        # exam_db 没有 update_question_status 方法，直接操作数据库
        import sqlite3
        from datetime import datetime

        conn = sqlite3.connect(exam_db.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO question_status
            (question_id, question_type, exam_id, status, affected_by, suggested_action, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (question_id, question_type, exam_id, status, affected_by, suggested_action,
              datetime.now().isoformat()))

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"更新题目状态失败: {e}")
        raise


def _generate_question_suggestions(
    document_id: str,
    change_details: Dict
) -> List[Dict]:
    """
    生成新题建议

    当文档有新增内容时，建议生成新题

    Args:
        document_id: 文档ID
        change_details: 变更详情

    Returns:
        新题建议列表
    """
    suggestions = []

    # 检查是否有新增章节
    added_sections = change_details.get("added_sections", [])

    for section in added_sections:
        suggestions.append({
            "type": "new_question",
            "document_id": document_id,
            "section": section,
            "reason": "新增内容，建议出题覆盖",
            "priority": "medium"
        })

    # 检查变更摘要中的关键词
    summary = change_details.get("change_summary", "")

    if "新规定" in summary or "新增" in summary:
        suggestions.append({
            "type": "new_question",
            "document_id": document_id,
            "section": "全文",
            "reason": "文档有新规定，建议出题覆盖",
            "priority": "high"
        })

    return suggestions


def _send_notifications(
    document_id: str,
    affected_questions: List[Dict],
    change_type: str
) -> int:
    """
    发送通知

    Args:
        document_id: 文档ID
        affected_questions: 受影响的题目列表
        change_type: 变更类型

    Returns:
        发送的通知数量
    """
    if not affected_questions:
        return 0

    try:
        import sqlite3
        from datetime import datetime

        # 写入通知表
        conn = sqlite3.connect("./data/sync_data.db")
        cursor = conn.cursor()

        # 确保通知表存在
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS maintenance_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                affected_count INTEGER NOT NULL,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read INTEGER DEFAULT 0
            )
        ''')

        message = f"文档 '{document_id}' 已{change_type}，{len(affected_questions)} 道题目需要审核"

        cursor.execute('''
            INSERT INTO maintenance_notifications
            (document_id, change_type, affected_count, message)
            VALUES (?, ?, ?, ?)
        ''', (document_id, change_type, len(affected_questions), message))

        conn.commit()
        conn.close()

        return 1

    except Exception as e:
        logger.warning(f"发送通知失败: {e}")
        return 0


def _format_question(q: Dict) -> Dict:
    """格式化题目信息用于返回"""
    return {
        "question_id": q.get("question_id"),
        "question_type": q.get("question_type"),
        "exam_id": q.get("exam_id"),
        "impact_level": q.get("impact_level", "unknown"),
        "suggested_action": q.get("suggested_action", ""),
        "reason": q.get("reason", "")
    }


# ==================== 便捷函数 ====================

def get_affected_questions(document_id: str) -> List[Dict]:
    """
    获取受影响的题目列表

    Args:
        document_id: 文档ID

    Returns:
        受影响的题目列表
    """
    try:
        from exam_analysis import ExamAnalysisDB

        exam_db = ExamAnalysisDB("./data/exam_analysis.db")
        return exam_db.get_document_questions(document_id) or []

    except ImportError:
        return []
    except Exception as e:
        logger.error(f"获取受影响题目失败: {e}")
        return []


def review_question(
    question_id: str,
    question_type: str,
    exam_id: str,
    action: str
) -> Dict:
    """
    审核受影响的题目

    Args:
        question_id: 题目ID
        question_type: 题目类型
        exam_id: 试卷ID
        action: 操作 (confirm/update/disable)

    Returns:
        审核结果
    """
    try:
        from exam_analysis import ExamAnalysisDB

        exam_db = ExamAnalysisDB("./data/exam_analysis.db")

        if action == "confirm":
            new_status = "approved"
        elif action == "disable":
            new_status = "disabled"
        else:
            new_status = "approved"

        exam_db.update_question_status(
            question_id=question_id,
            question_type=question_type,
            exam_id=exam_id,
            status=new_status
        )

        return {
            "success": True,
            "question_id": question_id,
            "new_status": new_status
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
