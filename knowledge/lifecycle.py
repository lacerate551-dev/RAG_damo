"""
文档生命周期管理 - 支持多向量库架构

功能：
1. 文档状态管理 - DRAFT/ACTIVE/DEPRECATED/SUPERSEDED
2. 版本追踪 - 记录文档版本历史
3. 软删除 - 废止文档但保留历史
4. 版本对比 - 对比不同版本的差异

使用方式：
    from document_lifecycle import DocumentLifecycleManager, DocumentStatus

    manager = DocumentLifecycleManager()

    # 废止文档
    result = manager.deprecate_document("dept_finance", "报销制度.pdf", "制度已更新")

    # 获取版本历史
    history = manager.get_document_history("dept_finance", "报销制度.pdf")

    # 获取生效版本
    active = manager.get_active_version("dept_finance", "报销制度.pdf")
"""

import os
import sqlite3
import logging
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 枚举与数据类 ====================

class DocumentStatus(Enum):
    """文档状态"""
    DRAFT = "draft"              # 草稿（上传但未同步）
    ACTIVE = "active"            # 生效中
    DEPRECATED = "deprecated"    # 已废止
    SUPERSEDED = "superseded"    # 被替代


@dataclass
class DocumentVersionInfo:
    """文档版本信息"""
    document_id: str             # 文档ID（文件名）
    collection: str              # 所属向量库
    version: str                 # 版本号
    status: DocumentStatus       # 状态
    effective_date: Optional[str] = None     # 生效日期
    deprecated_date: Optional[str] = None    # 废止日期
    deprecated_reason: Optional[str] = None  # 废止原因
    change_summary: Optional[str] = None     # 变更摘要
    supersedes: Optional[str] = None         # 替代的旧版本
    created_at: Optional[str] = None         # 创建时间
    created_by: Optional[str] = None         # 创建者
    chunk_count: int = 0                     # chunk数量

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


@dataclass
class VersionComparison:
    """版本对比结果"""
    old_version: str
    new_version: str
    added_chunks: int
    deleted_chunks: int
    modified_chunks: int
    unchanged_chunks: int
    impact_level: str            # high/medium/low/none
    impact_message: str
    details: Dict[str, Any]


# ==================== 文档生命周期管理器 ====================

class DocumentLifecycleManager:
    """
    文档生命周期管理器

    管理多向量库环境下的文档版本和状态。
    支持软删除、版本追踪、影响分析。
    """

    def __init__(self, db_path: str = "./data/exam_analysis.db"):
        """
        初始化

        Args:
            db_path: 数据库路径（与exam_analysis共用）
        """
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 文档版本表（扩展）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                collection TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT 'v1',
                status TEXT NOT NULL DEFAULT 'active',
                effective_date DATE,
                expiry_date DATE,
                deprecated_date DATETIME,
                deprecated_reason TEXT,
                deprecated_by TEXT,
                change_summary TEXT,
                supersedes TEXT,
                chunk_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                UNIQUE(document_id, collection, version)
            )
        ''')

        # 版本变更日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS version_change_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                collection TEXT NOT NULL,
                old_version TEXT,
                new_version TEXT,
                old_status TEXT,
                new_status TEXT,
                change_type TEXT NOT NULL,
                reason TEXT,
                changed_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"文档生命周期管理器初始化完成: {self.db_path}")

    # ==================== 废止操作 ====================

    def deprecate_document(
        self,
        collection: str,
        document_id: str,
        reason: str = "制度废止",
        deprecated_by: str = ""
    ) -> Dict:
        """
        废止文档（软删除）

        流程：
        1. 更新向量库元数据 status = 'deprecated'
        2. 更新版本记录
        3. 触发题库维护钩子
        4. 发送通知

        Args:
            collection: 向量库名称
            document_id: 文档ID（文件名）
            reason: 废止原因
            deprecated_by: 操作用户

        Returns:
            {
                "success": True,
                "deprecated_chunks": 15,
                "affected_questions": [...]
            }
        """
        from knowledge_base_manager import get_kb_manager

        kb_manager = get_kb_manager()

        # 1. 软删除向量库中的chunks
        result = kb_manager.deprecate_document(collection, document_id, reason, deprecated_by)

        if not result.get("success"):
            return result

        # 2. 更新版本记录
        self._update_version_status(
            collection=collection,
            document_id=document_id,
            new_status="deprecated",
            reason=reason,
            changed_by=deprecated_by
        )

        # 3. 触发题库钩子
        affected_questions = self._trigger_question_hook(
            collection, document_id, "DEPRECATED"
        )

        # 4. 记录变更日志
        self._log_version_change(
            collection=collection,
            document_id=document_id,
            change_type="deprecate",
            reason=reason,
            changed_by=deprecated_by
        )

        logger.info(f"文档已废止: {collection}/{document_id}, 原因: {reason}")

        return {
            "success": True,
            "deprecated_chunks": result.get("deprecated_chunks", 0),
            "document_id": document_id,
            "collection": collection,
            "affected_questions": affected_questions
        }

    def restore_document(
        self,
        collection: str,
        document_id: str,
        restored_by: str = ""
    ) -> Dict:
        """
        恢复已废止的文档

        Args:
            collection: 向量库名称
            document_id: 文档ID
            restored_by: 操作用户

        Returns:
            恢复结果
        """
        from knowledge_base_manager import get_kb_manager

        kb_manager = get_kb_manager()

        # 1. 恢复向量库中的chunks
        result = kb_manager.restore_document(collection, document_id)

        if not result.get("success"):
            return result

        # 2. 更新版本记录
        self._update_version_status(
            collection=collection,
            document_id=document_id,
            new_status="active",
            changed_by=restored_by
        )

        # 3. 记录变更日志
        self._log_version_change(
            collection=collection,
            document_id=document_id,
            change_type="restore",
            changed_by=restored_by
        )

        logger.info(f"文档已恢复: {collection}/{document_id}")

        return {
            "success": True,
            "restored_chunks": result.get("restored_chunks", 0),
            "document_id": document_id,
            "collection": collection
        }

    # ==================== 版本管理 ====================

    def update_document_version(
        self,
        collection: str,
        document_id: str,
        new_version: str,
        change_summary: str = "",
        changed_sections: List[str] = None,
        changed_by: str = ""
    ) -> Dict:
        """
        更新文档版本

        流程：
        1. 旧版本标记为 superseded
        2. 创建新版本记录
        3. 分析变更影响
        4. 触发题库审核流程

        Args:
            collection: 向量库名称
            document_id: 文档ID
            new_version: 新版本号
            change_summary: 变更摘要
            changed_sections: 变更的章节列表
            changed_by: 操作用户

        Returns:
            更新结果
        """
        # 获取当前版本
        current_version = self.get_active_version(collection, document_id)

        if current_version:
            # 旧版本标记为 superseded
            self._update_version_status(
                collection=collection,
                document_id=document_id,
                old_version=current_version.version,
                new_status="superseded",
                changed_by=changed_by
            )

        # 创建新版本记录
        self._create_version_record(
            collection=collection,
            document_id=document_id,
            version=new_version,
            status="active",
            change_summary=change_summary,
            supersedes=current_version.version if current_version else None,
            created_by=changed_by
        )

        # 触发题库审核
        affected = self._trigger_question_hook(
            collection, document_id, "MODIFIED",
            {"change_summary": change_summary, "changed_sections": changed_sections or []}
        )

        # 记录变更日志
        self._log_version_change(
            collection=collection,
            document_id=document_id,
            old_version=current_version.version if current_version else None,
            new_version=new_version,
            change_type="update",
            reason=change_summary,
            changed_by=changed_by
        )

        logger.info(f"文档版本更新: {collection}/{document_id} -> {new_version}")

        return {
            "success": True,
            "document_id": document_id,
            "collection": collection,
            "old_version": current_version.version if current_version else None,
            "new_version": new_version,
            "affected_questions": affected
        }

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
            版本历史列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT document_id, collection, version, status, effective_date,
                   deprecated_date, deprecated_reason, change_summary, supersedes,
                   created_at, created_by, chunk_count
            FROM document_versions
            WHERE document_id = ? AND collection = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (document_id, collection, limit))

        rows = cursor.fetchall()
        conn.close()

        return [
            DocumentVersionInfo(
                document_id=row[0],
                collection=row[1],
                version=row[2],
                status=DocumentStatus(row[3]) if row[3] in [s.value for s in DocumentStatus] else DocumentStatus.ACTIVE,
                effective_date=row[4],
                deprecated_date=row[5],
                deprecated_reason=row[6],
                change_summary=row[7],
                supersedes=row[8],
                created_at=row[9],
                created_by=row[10],
                chunk_count=row[11] or 0
            )
            for row in rows
        ]

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
            生效版本信息，不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT document_id, collection, version, status, effective_date,
                   deprecated_date, deprecated_reason, change_summary, supersedes,
                   created_at, created_by, chunk_count
            FROM document_versions
            WHERE document_id = ? AND collection = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        ''', (document_id, collection))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return DocumentVersionInfo(
            document_id=row[0],
            collection=row[1],
            version=row[2],
            status=DocumentStatus.ACTIVE,
            effective_date=row[4],
            deprecated_date=row[5],
            deprecated_reason=row[6],
            change_summary=row[7],
            supersedes=row[8],
            created_at=row[9],
            created_by=row[10],
            chunk_count=row[11] or 0
        )

    def list_deprecated_documents(
        self,
        collection: str = None,
        limit: int = 50
    ) -> List[DocumentVersionInfo]:
        """
        列出已废止的文档

        Args:
            collection: 向量库名称（可选，不传则查所有）
            limit: 返回数量限制

        Returns:
            已废止文档列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if collection:
            cursor.execute('''
                SELECT document_id, collection, version, status, effective_date,
                       deprecated_date, deprecated_reason, change_summary, supersedes,
                       created_at, created_by, chunk_count
                FROM document_versions
                WHERE collection = ? AND status = 'deprecated'
                ORDER BY deprecated_date DESC
                LIMIT ?
            ''', (collection, limit))
        else:
            cursor.execute('''
                SELECT document_id, collection, version, status, effective_date,
                       deprecated_date, deprecated_reason, change_summary, supersedes,
                       created_at, created_by, chunk_count
                FROM document_versions
                WHERE status = 'deprecated'
                ORDER BY deprecated_date DESC
                LIMIT ?
            ''', (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [
            DocumentVersionInfo(
                document_id=row[0],
                collection=row[1],
                version=row[2],
                status=DocumentStatus.DEPRECATED,
                effective_date=row[4],
                deprecated_date=row[5],
                deprecated_reason=row[6],
                change_summary=row[7],
                supersedes=row[8],
                created_at=row[9],
                created_by=row[10],
                chunk_count=row[11] or 0
            )
            for row in rows
        ]

    # ==================== 内部方法 ====================

    def _update_version_status(
        self,
        collection: str,
        document_id: str,
        new_status: str,
        reason: str = "",
        old_version: str = None,
        changed_by: str = ""
    ):
        """更新版本状态"""
        from datetime import datetime

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now().isoformat()

        if new_status == "deprecated":
            cursor.execute('''
                UPDATE document_versions
                SET status = ?, deprecated_date = ?, deprecated_reason = ?, deprecated_by = ?
                WHERE document_id = ? AND collection = ? AND status = 'active'
            ''', (new_status, now, reason, changed_by, document_id, collection))
        elif new_status == "superseded":
            cursor.execute('''
                UPDATE document_versions
                SET status = ?, expiry_date = ?
                WHERE document_id = ? AND collection = ? AND status = 'active'
            ''', (new_status, now[:10], document_id, collection))
        elif new_status == "active":
            cursor.execute('''
                UPDATE document_versions
                SET status = ?, deprecated_date = NULL, deprecated_reason = NULL
                WHERE document_id = ? AND collection = ?
            ''', (new_status, document_id, collection))

        conn.commit()
        conn.close()

    def _create_version_record(
        self,
        collection: str,
        document_id: str,
        version: str,
        status: str = "active",
        change_summary: str = "",
        supersedes: str = None,
        created_by: str = ""
    ):
        """创建版本记录"""
        from datetime import datetime

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now()

        cursor.execute('''
            INSERT OR REPLACE INTO document_versions
            (document_id, collection, version, status, effective_date, change_summary, supersedes, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (document_id, collection, version, status, now.strftime("%Y-%m-%d"),
              change_summary, supersedes, created_by))

        conn.commit()
        conn.close()

    def _log_version_change(
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
        """记录版本变更日志"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO version_change_logs
            (document_id, collection, old_version, new_version, old_status, new_status, change_type, reason, changed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (document_id, collection, old_version, new_version, old_status, new_status,
              change_type, reason, changed_by))

        conn.commit()
        conn.close()

    def _trigger_question_hook(
        self,
        collection: str,
        document_id: str,
        change_type: str,
        change_details: Dict = None
    ) -> List[Dict]:
        """
        触发题库维护钩子

        Args:
            collection: 向量库名称
            document_id: 文档ID
            change_type: 变更类型
            change_details: 变更详情

        Returns:
            受影响的题目列表
        """
        try:
            from question_maintenance_hook import on_knowledge_base_change

            result = on_knowledge_base_change(
                collection=collection,
                document_id=document_id,
                change_type=change_type,
                change_details=change_details or {}
            )

            return result.get("affected_questions", [])

        except ImportError:
            logger.warning("题库维护钩子模块未安装")
            return []
        except Exception as e:
            logger.error(f"触发题库钩子失败: {e}")
            return []


# ==================== 全局实例 ====================

_lifecycle_manager: Optional[DocumentLifecycleManager] = None


def get_lifecycle_manager() -> DocumentLifecycleManager:
    """获取全局生命周期管理器实例"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = DocumentLifecycleManager()
    return _lifecycle_manager
