"""
审计日志模块 - 记录用户操作行为

功能：
1. 记录查询日志（谁、什么时间、查了什么）
2. 记录检索结果（返回了哪些文档）
3. 记录文档访问（哪些文档被哪些用户查看）
4. 支持按用户、时间范围查询日志

使用方式：
    from services.audit import AuditLogger

    logger = AuditLogger()
    logger.log_query(user_id, query, result_summary, sources)
    logs = logger.get_user_logs(user_id)
"""

import json
from datetime import datetime
from typing import Optional, List, Dict

from data.db import get_connection


class AuditLogger:
    """审计日志记录器"""

    def __init__(self):
        from data.db import init_databases
        init_databases()

    def log(self, user_id: str, action: str, resource: str = "",
            details: Dict = None, username: str = "", role: str = "",
            department: str = "", ip_address: str = "") -> int:
        """
        记录通用操作日志（非查询类操作）

        Args:
            user_id: 用户ID
            action: 操作类型（upload_document/delete_document/deprecate_document等）
            resource: 操作资源（如文件路径）
            details: 操作详情字典
            username: 用户名
            role: 用户角色
            department: 部门
            ip_address: 请求IP

        Returns:
            日志记录ID
        """
        details_json = json.dumps(details or {}, ensure_ascii=False)[:2000]

        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO audit_logs
                (user_id, username, action, query, result_summary, sources,
                 role, department, ip_address, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, action, resource, "", details_json,
                role, department, ip_address, 0
            ))

            log_id = cursor.lastrowid

        return log_id

    def log_query(self, user_id: str, query: str,
                  result_summary: str = "", sources: List[Dict] = None,
                  username: str = "", role: str = "", department: str = "",
                  action: str = "query", ip_address: str = "",
                  duration_ms: int = 0) -> int:
        """
        记录查询日志

        Args:
            user_id: 用户ID
            query: 查询内容
            result_summary: 回答摘要
            sources: 来源文档列表
            username: 用户名
            role: 用户角色
            department: 部门
            action: 操作类型（query/chat/search/graph_search）
            ip_address: 请求IP
            duration_ms: 处理耗时(毫秒)

        Returns:
            日志记录ID
        """
        # 截断过长的内容
        summary = (result_summary[:500] + "...") if len(result_summary) > 500 else result_summary
        sources_json = json.dumps(sources or [], ensure_ascii=False)[:2000]

        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO audit_logs
                (user_id, username, action, query, result_summary, sources,
                 role, department, ip_address, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, action, query, summary, sources_json,
                role, department, ip_address, duration_ms
            ))

            log_id = cursor.lastrowid

        return log_id

    def get_user_logs(self, user_id: str, limit: int = 50,
                      offset: int = 0) -> List[Dict]:
        """获取用户的操作日志"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, user_id, username, action, query, result_summary,
                       sources, role, department, ip_address, duration_ms, created_at
                FROM audit_logs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            ''', (user_id, limit, offset))

            rows = cursor.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_recent_logs(self, limit: int = 100, action: str = None) -> List[Dict]:
        """获取最近的操作日志"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            if action:
                cursor.execute('''
                    SELECT id, user_id, username, action, query, result_summary,
                           sources, role, department, ip_address, duration_ms, created_at
                    FROM audit_logs
                    WHERE action = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (action, limit))
            else:
                cursor.execute('''
                    SELECT id, user_id, username, action, query, result_summary,
                           sources, role, department, ip_address, duration_ms, created_at
                    FROM audit_logs
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))

            rows = cursor.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_logs_by_date_range(self, start_date: str, end_date: str,
                               user_id: str = None) -> List[Dict]:
        """按日期范围查询日志"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            if user_id:
                cursor.execute('''
                    SELECT id, user_id, username, action, query, result_summary,
                           sources, role, department, ip_address, duration_ms, created_at
                    FROM audit_logs
                    WHERE created_at BETWEEN ? AND ? AND user_id = ?
                    ORDER BY created_at DESC
                ''', (start_date, end_date, user_id))
            else:
                cursor.execute('''
                    SELECT id, user_id, username, action, query, result_summary,
                           sources, role, department, ip_address, duration_ms, created_at
                    FROM audit_logs
                    WHERE created_at BETWEEN ? AND ?
                    ORDER BY created_at DESC
                ''', (start_date, end_date))

            rows = cursor.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_document_access_stats(self, limit: int = 20) -> List[Dict]:
        """获取文档访问统计（哪些文档被查询最多）"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    json_extract(value, '$.source') as doc_source,
                    COUNT(*) as access_count
                FROM audit_logs, json_each(sources)
                WHERE json_valid(sources) AND sources != '[]'
                GROUP BY doc_source
                ORDER BY access_count DESC
                LIMIT ?
            ''', (limit,))

            rows = cursor.fetchall()

        return [{"source": r[0], "access_count": r[1]} for r in rows if r[0]]

    def get_user_stats(self) -> List[Dict]:
        """获取用户活跃度统计"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT user_id, username, role, department,
                       COUNT(*) as query_count,
                       MIN(created_at) as first_seen,
                       MAX(created_at) as last_seen
                FROM audit_logs
                GROUP BY user_id
                ORDER BY query_count DESC
            ''')

            rows = cursor.fetchall()

        return [
            {
                "user_id": r[0], "username": r[1], "role": r[2],
                "department": r[3], "query_count": r[4],
                "first_seen": r[5], "last_seen": r[6]
            }
            for r in rows
        ]

    def cleanup_old_logs(self, days: int = 90) -> int:
        """清理指定天数之前的日志"""
        with get_connection("core") as conn:
            cursor = conn.cursor()

            cursor.execute('''
                DELETE FROM audit_logs
                WHERE created_at < datetime('now', ?)
            ''', (f'-{days} days',))

            deleted = cursor.rowcount

        return deleted

    @staticmethod
    def _row_to_dict(row) -> Dict:
        """将数据库行转为字典"""
        return {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "action": row[3],
            "query": row[4],
            "result_summary": row[5],
            "sources": json.loads(row[6]) if row[6] else [],
            "role": row[7],
            "department": row[8],
            "ip_address": row[9],
            "duration_ms": row[10],
            "created_at": row[11]
        }
