"""
文档版本查询模块（简化版）

保留核心的版本查询功能，删除未使用的生命周期管理功能。

功能：
1. 查询文档版本历史
2. 获取当前生效版本
3. 记录版本变更日志

使用方式：
    from knowledge.document_versions import DocumentVersionQuery

    query = DocumentVersionQuery()

    # 获取版本历史
    history = query.get_document_history("public_kb", "报销制度.pdf")

    # 获取生效版本
    active = query.get_active_version("public_kb", "报销制度.pdf")
"""

import logging
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict

from data.db import get_connection

logger = logging.getLogger(__name__)


# ==================== 枚举与数据类 ====================

class DocumentStatus(Enum):
    """文档状态"""
    DRAFT = "draft"              # 草稿
    ACTIVE = "active"            # 生效中
    DEPRECATED = "deprecated"    # 已废止
    SUPERSEDED = "superseded"    # 被替代


@dataclass
class DocumentVersionInfo:
    """文档版本信息"""
    document_id: str
    collection: str
    version: str
    status: DocumentStatus
    effective_date: Optional[str] = None
    deprecated_date: Optional[str] = None
    deprecated_reason: Optional[str] = None
    change_summary: Optional[str] = None
    supersedes: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    chunk_count: int = 0

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "document_id": self.document_id,
            "collection": self.collection,
            "version": self.version,
            "status": self.status.value if isinstance(self.status, DocumentStatus) else self.status,
            "effective_date": self.effective_date,
            "deprecated_date": self.deprecated_date,
            "deprecated_reason": self.deprecated_reason,
            "change_summary": self.change_summary,
            "supersedes": self.supersedes,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "chunk_count": self.chunk_count
        }


# ==================== 文档版本查询 ====================

class DocumentVersionQuery:
    """文档版本查询（简化版）"""

    def __init__(self):
        """初始化"""
        pass

    def get_document_history(
        self,
        collection: str,
        document_id: str,
        limit: int = 10
    ) -> List[DocumentVersionInfo]:
        """
        获取文档版本历史

        Args:
            collection: 向量库名称
            document_id: 文档ID
            limit: 返回数量限制

        Returns:
            版本信息列表（按时间倒序）
        """
        try:
            with get_connection("knowledge") as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        document_id, collection, version, status,
                        effective_date, deprecated_date, deprecated_reason,
                        change_summary, supersedes, created_at, created_by,
                        chunk_count
                    FROM document_versions
                    WHERE collection = ? AND document_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (collection, document_id, limit)
                )

                versions = []
                for row in cursor.fetchall():
                    versions.append(DocumentVersionInfo(
                        document_id=row[0],
                        collection=row[1],
                        version=row[2],
                        status=DocumentStatus(row[3]) if row[3] else DocumentStatus.ACTIVE,
                        effective_date=row[4],
                        deprecated_date=row[5],
                        deprecated_reason=row[6],
                        change_summary=row[7],
                        supersedes=row[8],
                        created_at=row[9],
                        created_by=row[10],
                        chunk_count=row[11] or 0
                    ))

                return versions

        except Exception as e:
            logger.error(f"获取文档历史失败: {e}")
            return []

    def get_active_version(
        self,
        collection: str,
        document_id: str
    ) -> Optional[DocumentVersionInfo]:
        """
        获取当前生效版本

        Args:
            collection: 向量库名称
            document_id: 文档ID

        Returns:
            生效版本信息，不存在则返回 None
        """
        try:
            with get_connection("knowledge") as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        document_id, collection, version, status,
                        effective_date, deprecated_date, deprecated_reason,
                        change_summary, supersedes, created_at, created_by,
                        chunk_count
                    FROM document_versions
                    WHERE collection = ? AND document_id = ? AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (collection, document_id)
                )

                row = cursor.fetchone()
                if row:
                    return DocumentVersionInfo(
                        document_id=row[0],
                        collection=row[1],
                        version=row[2],
                        status=DocumentStatus(row[3]) if row[3] else DocumentStatus.ACTIVE,
                        effective_date=row[4],
                        deprecated_date=row[5],
                        deprecated_reason=row[6],
                        change_summary=row[7],
                        supersedes=row[8],
                        created_at=row[9],
                        created_by=row[10],
                        chunk_count=row[11] or 0
                    )

                return None

        except Exception as e:
            logger.error(f"获取生效版本失败: {e}")
            return None

    def get_next_version(self, collection: str, document_id: str) -> str:
        """
        获取下一个版本号

        Args:
            collection: 向量库名称
            document_id: 文档ID

        Returns:
            版本号字符串，如 'v1', 'v2', 'v3'
        """
        try:
            with get_connection("knowledge") as conn:
                cursor = conn.execute(
                    """
                    SELECT version FROM document_versions
                    WHERE collection = ? AND document_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (collection, document_id)
                )
                row = cursor.fetchone()

                if row and row[0]:
                    # 解析现有版本号
                    current = row[0]
                    if current.startswith('v') and current[1:].isdigit():
                        next_num = int(current[1:]) + 1
                    else:
                        # 非标准版本号，从1开始
                        next_num = 1
                else:
                    next_num = 1

                return f"v{next_num}"

        except Exception as e:
            logger.warning(f"获取版本号失败: {e}，使用默认 v1")
            return "v1"

    def create_version_record(
        self,
        collection: str,
        document_id: str,
        version: str = None,
        status: str = "active",
        change_summary: str = "",
        supersedes: str = None,
        created_by: str = "",
        chunk_count: int = 0
    ):
        """
        创建版本记录

        Args:
            collection: 向量库名称
            document_id: 文档ID
            version: 版本号（可选，不传则自动生成 v1, v2, v3...）
            status: 状态
            change_summary: 变更摘要
            supersedes: 替代的旧版本
            created_by: 创建者
            chunk_count: chunk数量
        """
        # 自动生成版本号
        if version is None:
            version = self.get_next_version(collection, document_id)

        try:
            with get_connection("knowledge") as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO document_versions
                    (document_id, collection, version, status, effective_date,
                     change_summary, supersedes, created_at, created_by, chunk_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        collection,
                        version,
                        status,
                        datetime.now().isoformat(),
                        change_summary,
                        supersedes,
                        datetime.now().isoformat(),
                        created_by,
                        chunk_count
                    )
                )
                conn.commit()
                logger.info(f"创建版本记录: {collection}/{document_id} {version}")

        except Exception as e:
            logger.error(f"创建版本记录失败: {e}")
            raise

    def log_version_change(
        self,
        collection: str,
        document_id: str,
        change_type: str,
        old_version: str = None,
        new_version: str = None,
        old_status: str = None,
        new_status: str = None,
        reason: str = "",
        changed_by: str = ""
    ):
        """
        记录版本变更日志

        Args:
            collection: 向量库名称
            document_id: 文档ID
            change_type: 变更类型（update/deprecate/restore）
            old_version: 旧版本号
            new_version: 新版本号
            old_status: 旧状态
            new_status: 新状态
            reason: 变更原因
            changed_by: 操作者
        """
        try:
            with get_connection("knowledge") as conn:
                conn.execute(
                    """
                    INSERT INTO version_change_logs
                    (document_id, collection, old_version, new_version,
                     old_status, new_status, change_type, reason, changed_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        collection,
                        old_version,
                        new_version,
                        old_status,
                        new_status,
                        change_type,
                        reason,
                        changed_by,
                        datetime.now().isoformat()
                    )
                )
                conn.commit()
                logger.info(f"记录版本变更: {collection}/{document_id} {change_type}")

        except Exception as e:
            logger.error(f"记录版本变更失败: {e}")


# ==================== 工厂函数 ====================

_version_query_instance = None

def get_version_query() -> DocumentVersionQuery:
    """获取文档版本查询实例（单例）"""
    global _version_query_instance
    if _version_query_instance is None:
        _version_query_instance = DocumentVersionQuery()
    return _version_query_instance
