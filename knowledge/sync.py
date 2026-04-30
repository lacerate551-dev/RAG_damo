"""
知识库同步服务 - 自动检测文档变更并触发增量更新

功能：
1. 文件变更监控 - 使用 watchdog 监控 documents 目录
2. 哈希比对 - 识别文件具体变更类型（新增/修改/删除）
3. 增量向量化 - 仅处理变更文件
4. 变更日志 - 记录变更历史

使用方式：
    from knowledge.sync import KnowledgeSyncService

    # 启动同步服务
    sync_service = KnowledgeSyncService()
    sync_service.start()  # 启动后台监控

    # 手动触发同步
    result = sync_service.sync_now()
"""

import os
import sys
import json
import hashlib
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from data.db import get_connection, init_databases

# 缓存支持
try:
    from core.cache import get_cache_manager
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 尝试导入 watchdog
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    logger.warning("watchdog 未安装，文件监控功能不可用。请运行: pip install watchdog")


class ChangeType(Enum):
    """变更类型"""
    ADDED = "added"       # 新增
    MODIFIED = "modified" # 修改
    DELETED = "deleted"   # 删除


class SyncStatus(Enum):
    """同步状态"""
    IDLE = "idle"           # 空闲
    RUNNING = "running"     # 运行中
    COMPLETED = "completed" # 已完成
    FAILED = "failed"       # 失败


@dataclass
class DocumentChange:
    """文档变更记录"""
    document_id: str           # 文档ID（相对路径）
    document_name: str         # 文件名
    change_type: ChangeType    # 变更类型
    old_hash: Optional[str]    # 旧哈希
    new_hash: Optional[str]    # 新哈希
    change_time: datetime      # 变更时间
    processed: bool = False    # 是否已处理
    error_message: Optional[str] = None

    def to_dict(self):
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "change_type": self.change_type.value,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "change_time": self.change_time.isoformat(),
            "processed": self.processed,
            "error_message": self.error_message
        }


@dataclass
class SyncResult:
    """同步结果"""
    status: SyncStatus
    start_time: datetime
    end_time: Optional[datetime]
    documents_processed: int
    documents_added: int
    documents_modified: int
    documents_deleted: int
    errors: List[str]

    def to_dict(self):
        return {
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "documents_processed": self.documents_processed,
            "documents_added": self.documents_added,
            "documents_modified": self.documents_modified,
            "documents_deleted": self.documents_deleted,
            "errors": self.errors
        }


class SyncDatabase:
    """同步数据库管理"""

    def __init__(self):
        """初始化数据库"""
        init_databases()

    def get_document_hash(self, document_id: str) -> Optional[Dict]:
        """获取文档的当前哈希"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT document_id, document_name, content_hash, file_size, last_modified
                FROM document_hashes WHERE document_id = ?
            ''', (document_id,))
            row = cursor.fetchone()

            if row:
                return {
                    "document_id": row[0],
                    "document_name": row[1],
                    "content_hash": row[2],
                    "file_size": row[3],
                    "last_modified": row[4]
                }
            return None

    def set_document_hash(self, document_id: str, document_name: str,
                          content_hash: str, file_size: int, last_modified: datetime):
        """设置文档哈希"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO document_hashes
                (document_id, document_name, content_hash, file_size, last_modified, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (document_id, document_name, content_hash, file_size, last_modified))

    def delete_document_hash(self, document_id: str):
        """删除文档哈希记录"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM document_hashes WHERE document_id = ?', (document_id,))

    def get_all_document_hashes(self) -> Dict[str, Dict]:
        """获取所有文档哈希"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT document_id, document_name, content_hash, file_size, last_modified
                FROM document_hashes
            ''')
            rows = cursor.fetchall()

            return {
                row[0]: {
                    "document_id": row[0],
                    "document_name": row[1],
                    "content_hash": row[2],
                    "file_size": row[3],
                    "last_modified": row[4]
                }
                for row in rows
            }

    def log_change(self, change: DocumentChange) -> int:
        """记录变更"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO change_logs
                (document_id, document_name, change_type, old_hash, new_hash, change_time, processed, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                change.document_id,
                change.document_name,
                change.change_type.value,
                change.old_hash,
                change.new_hash,
                change.change_time,
                change.processed,
                change.error_message
            ))
            return cursor.lastrowid

    def get_change_logs(self, limit: int = 100, processed: Optional[bool] = None,
                        days: int = 30) -> List[Dict]:
        """获取变更日志"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()

            sql = '''
                SELECT id, document_id, document_name, change_type, old_hash, new_hash,
                       change_time, processed, error_message
                FROM change_logs
                WHERE change_time >= datetime('now', ?)
            '''
            params = [f'-{days} days']

            if processed is not None:
                sql += ' AND processed = ?'
                params.append(1 if processed else 0)

            sql += ' ORDER BY change_time DESC LIMIT ?'
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "document_id": row[1],
                    "document_name": row[2],
                    "change_type": row[3],
                    "old_hash": row[4],
                    "new_hash": row[5],
                    "change_time": row[6],
                    "processed": bool(row[7]),
                    "error_message": row[8]
                }
                for row in rows
            ]

    def mark_change_processed(self, change_id: int, error_message: str = None):
        """标记变更已处理"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE change_logs
                SET processed = 1, error_message = ?
                WHERE id = ?
            ''', (error_message, change_id))

    def log_sync_status(self, result: SyncResult) -> int:
        """记录同步状态"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sync_status
                (sync_type, status, start_time, end_time, documents_processed,
                 documents_added, documents_modified, documents_deleted, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                "incremental",
                result.status.value,
                result.start_time,
                result.end_time,
                result.documents_processed,
                result.documents_added,
                result.documents_modified,
                result.documents_deleted,
                "; ".join(result.errors) if result.errors else None
            ))
            return cursor.lastrowid

    def get_sync_history(self, limit: int = 20) -> List[Dict]:
        """获取同步历史"""
        with get_connection("knowledge") as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, sync_type, status, start_time, end_time,
                       documents_processed, documents_added, documents_modified, documents_deleted, error_message
                FROM sync_status
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))
            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "sync_type": row[1],
                    "status": row[2],
                    "start_time": row[3],
                    "end_time": row[4],
                    "documents_processed": row[5],
                    "documents_added": row[6],
                    "documents_modified": row[7],
                    "documents_deleted": row[8],
                    "error_message": row[9]
                }
                for row in rows
            ]


class FileChangeHandler(FileSystemEventHandler if HAS_WATCHDOG else object):
    """文件变更处理器"""

    def __init__(self, sync_service: 'KnowledgeSyncService'):
        if HAS_WATCHDOG:
            super().__init__()
        self.sync_service = sync_service
        # v5 统一解析支持的所有格式
        self.supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.txt', '.png', '.jpg', '.jpeg', '.bmp', '.tiff'}
        self._pending_changes = {}  # 防抖：短时间内多次修改只记录一次
        self._debounce_seconds = 2

    def _is_supported_file(self, file_path: str) -> bool:
        """检查是否为支持的文件类型"""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.supported_extensions

    def _debounce_change(self, file_path: str, change_type: ChangeType):
        """防抖处理：短时间内多次修改合并为一次"""
        current_time = time.time()

        if file_path in self._pending_changes:
            last_time, last_type = self._pending_changes[file_path]
            # 如果是修改事件且距离上次事件很近，忽略
            if current_time - last_time < self._debounce_seconds:
                return

        self._pending_changes[file_path] = (current_time, change_type)

        # 延迟处理
        threading.Timer(self._debounce_seconds, self._process_change, args=[file_path, change_type]).start()

    def _process_change(self, file_path: str, change_type: ChangeType):
        """处理文件变更"""
        try:
            # 计算相对路径
            rel_path = os.path.relpath(file_path, self.sync_service.documents_path)
            document_name = os.path.basename(file_path)

            logger.info(f"检测到文件变更: {rel_path} ({change_type.value})")

            # 创建变更记录
            change = DocumentChange(
                document_id=rel_path,
                document_name=document_name,
                change_type=change_type,
                old_hash=None,
                new_hash=None,
                change_time=datetime.now()
            )

            # 获取旧哈希
            old_doc = self.sync_service.db.get_document_hash(rel_path)
            if old_doc:
                change.old_hash = old_doc['content_hash']

            # 计算新哈希（如果不是删除）
            if change_type != ChangeType.DELETED and os.path.exists(file_path):
                change.new_hash = self.sync_service.calculate_file_hash(file_path)

            # 记录变更
            self.sync_service.db.log_change(change)

            # 触发回调
            if self.sync_service.on_change_callback:
                self.sync_service.on_change_callback(change)

        except Exception as e:
            logger.error(f"处理文件变更失败: {file_path}, 错误: {e}")

    def on_created(self, event):
        """文件创建事件"""
        if event.is_directory:
            return
        if not self._is_supported_file(event.src_path):
            return
        self._debounce_change(event.src_path, ChangeType.ADDED)

    def on_modified(self, event):
        """文件修改事件"""
        if event.is_directory:
            return
        if not self._is_supported_file(event.src_path):
            return
        self._debounce_change(event.src_path, ChangeType.MODIFIED)

    def on_deleted(self, event):
        """文件删除事件"""
        if event.is_directory:
            return
        if not self._is_supported_file(event.src_path):
            return
        self._debounce_change(event.src_path, ChangeType.DELETED)

    def on_moved(self, event):
        """文件移动事件"""
        if event.is_directory:
            return
        # 移动视为删除旧文件 + 创建新文件
        if self._is_supported_file(event.src_path):
            self._debounce_change(event.src_path, ChangeType.DELETED)
        if self._is_supported_file(event.dest_path):
            self._debounce_change(event.dest_path, ChangeType.ADDED)


class KnowledgeSyncService:
    """知识库同步服务"""

    def __init__(self, documents_path: str = None):
        """
        初始化同步服务

        Args:
            documents_path: 文档目录路径，默认为 ./documents
        """
        self.documents_path = documents_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "documents"
        )
        self.db = SyncDatabase()

        self._observer = None
        self._running = False
        self.on_change_callback: Optional[Callable] = None
        self.on_sync_callback: Optional[Callable] = None



    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """计算文件哈希"""
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"计算文件哈希失败: {file_path}, 错误: {e}")
            return ""

    def scan_documents(self) -> Dict[str, Dict]:
        """扫描文档目录，返回所有文档信息"""
        documents = {}
        # v5 统一解析支持的所有格式
        supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.txt', '.png', '.jpg', '.jpeg', '.bmp', '.tiff'}

        for root, dirs, files in os.walk(self.documents_path):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in supported_extensions:
                    continue

                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, self.documents_path)

                try:
                    file_stat = os.stat(file_path)
                    documents[rel_path] = {
                        "document_id": rel_path,
                        "document_name": filename,
                        "file_path": file_path,
                        "file_size": file_stat.st_size,
                        "last_modified": datetime.fromtimestamp(file_stat.st_mtime),
                        "content_hash": self.calculate_file_hash(file_path)
                    }
                except Exception as e:
                    logger.error(f"扫描文档失败: {rel_path}, 错误: {e}")

        return documents

    def detect_changes(self) -> List[DocumentChange]:
        """检测文档变更"""
        changes = []
        current_docs = self.scan_documents()
        stored_docs = self.db.get_all_document_hashes()

        current_ids = set(current_docs.keys())
        stored_ids = set(stored_docs.keys())

        # 新增的文档
        for doc_id in current_ids - stored_ids:
            doc = current_docs[doc_id]
            changes.append(DocumentChange(
                document_id=doc_id,
                document_name=doc["document_name"],
                change_type=ChangeType.ADDED,
                old_hash=None,
                new_hash=doc["content_hash"],
                change_time=datetime.now()
            ))

        # 删除的文档
        for doc_id in stored_ids - current_ids:
            doc = stored_docs[doc_id]
            changes.append(DocumentChange(
                document_id=doc_id,
                document_name=doc["document_name"],
                change_type=ChangeType.DELETED,
                old_hash=doc["content_hash"],
                new_hash=None,
                change_time=datetime.now()
            ))

        # 修改的文档
        for doc_id in current_ids & stored_ids:
            current_doc = current_docs[doc_id]
            stored_doc = stored_docs[doc_id]

            if current_doc["content_hash"] != stored_doc["content_hash"]:
                changes.append(DocumentChange(
                    document_id=doc_id,
                    document_name=current_doc["document_name"],
                    change_type=ChangeType.MODIFIED,
                    old_hash=stored_doc["content_hash"],
                    new_hash=current_doc["content_hash"],
                    change_time=datetime.now()
                ))

        return changes

    def process_change(self, change: DocumentChange) -> bool:
        """处理单个变更"""
        try:
            file_path = os.path.join(self.documents_path, change.document_id)

            # 从 document_id 中解析目标向量库
            # document_id 格式: "public/filename.pdf" 或 "finance/filename.pdf"
            kb_name = self._get_kb_name_from_path(change.document_id)

            # 导入知识库管理器
            from knowledge.manager import get_kb_manager
            kb_manager = get_kb_manager()

            if change.change_type == ChangeType.ADDED:
                # 新增文档 - 使用多向量库方法
                chunks_added = kb_manager.add_file_to_kb(
                    kb_name=kb_name,
                    filepath=file_path,
                    extra_metadata={
                        'status': 'active',
                        'version': 'v1',
                        'change_time': datetime.now().isoformat()
                    }
                )
                # 更新哈希记录
                self.db.set_document_hash(
                    change.document_id,
                    change.document_name,
                    change.new_hash,
                    os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    datetime.now()
                )

                # 创建版本记录
                try:
                    from knowledge.document_versions import get_version_query
                    version_query = get_version_query()
                    version_query.create_version_record(
                        collection=kb_name,
                        document_id=change.document_name,
                        version="v1",
                        status="active",
                        change_summary="新增文档",
                        created_by="sync_service",
                        chunk_count=chunks_added
                    )
                except Exception as e:
                    logger.warning(f"创建版本记录失败: {e}")

                logger.info(f"已添加文档到 {kb_name}: {change.document_id}, 片段数: {chunks_added}")

            elif change.change_type == ChangeType.MODIFIED:
                # 修改文档：使用版本管理策略
                # 1. 获取当前版本号
                old_version = self._get_current_version(kb_name, change.document_name)

                # 2. 标记旧版本为 superseded（如果存在）
                if old_version:
                    try:
                        kb_manager.mark_document_as_superseded(
                            kb_name,
                            change.document_name,
                            reason="文档更新"
                        )
                        logger.info(f"标记旧版本为 superseded: {change.document_name} {old_version}")
                    except Exception as e:
                        logger.warning(f"标记旧版本失败: {e}")

                # 3. 生成新版本号
                new_version = self._generate_version_id(kb_name, change.document_name)

                # 4. 添加新版本
                chunks_added = kb_manager.add_file_to_kb(
                    kb_name=kb_name,
                    filepath=file_path,
                    extra_metadata={
                        'status': 'active',
                        'version': new_version,
                        'previous_version': old_version or '',
                        'change_time': datetime.now().isoformat()
                    }
                )

                # 5. 更新哈希记录
                self.db.set_document_hash(
                    change.document_id,
                    change.document_name,
                    change.new_hash,
                    os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    datetime.now()
                )

                # 6. 记录版本变更
                if old_version:
                    self._record_version_change(
                        kb_name,
                        change.document_name,
                        old_version,
                        new_version,
                        "文档更新"
                    )

                logger.info(f"已更新文档: {change.document_id}, 版本: {old_version} → {new_version}, 添加 {chunks_added} 片段")

            elif change.change_type == ChangeType.DELETED:
                # 删除文档
                deleted = kb_manager.delete_document(kb_name, change.document_name)
                # 删除哈希记录
                self.db.delete_document_hash(change.document_id)
                logger.info(f"已删除文档: {change.document_id}, 删除 {deleted} 片段")

            # ==================== 缓存失效 ====================
            # 文档变更后递增知识库版本号，使旧缓存自动失效
            if CACHE_AVAILABLE:
                try:
                    cache = get_cache_manager()
                    cache.increment_kb_version(kb_name)
                    logger.debug(f"已递增知识库版本号: {kb_name}")
                except Exception as e:
                    logger.warning(f"递增缓存版本号失败: {e}")

            return True

        except Exception as e:
            logger.error(f"处理变更失败: {change.document_id}, 错误: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_kb_name_from_path(self, document_id: str) -> str:
        """
        从文档ID中解析目标向量库名称

        Args:
            document_id: 文档ID，格式如 "public_kb/filename.pdf" 或 "dept_hr/filename.pdf"

        Returns:
            向量库名称（目录名 = 向量库名）
        """
        # 统一路径分隔符（兼容 Windows 和 Linux）
        normalized = document_id.replace('\\', '/')
        # 获取第一级目录名（即向量库名）
        parts = normalized.split('/')
        if len(parts) > 1:
            return parts[0]  # 目录名即向量库名
        else:
            return 'public_kb'  # 默认公开库

    def _get_current_version(self, kb_name: str, filename: str) -> str:
        """
        获取文档当前版本号

        Args:
            kb_name: 知识库名称
            filename: 文件名

        Returns:
            当前版本号，如 "v1", "v2"，不存在则返回 None
        """
        try:
            from knowledge.document_versions import get_version_query
            version_query = get_version_query()
            active_version = version_query.get_active_version(kb_name, filename)
            return active_version.version if active_version else None
        except Exception as e:
            logger.warning(f"获取当前版本失败: {e}")
            return None

    def _generate_version_id(self, kb_name: str, filename: str) -> str:
        """
        生成新版本号

        Args:
            kb_name: 知识库名称
            filename: 文件名

        Returns:
            新版本号，如 "v1", "v2", "v3"
        """
        current_version = self._get_current_version(kb_name, filename)
        if not current_version:
            return "v1"

        # 从 "v1" 提取数字并递增
        try:
            version_num = int(current_version.replace('v', ''))
            return f"v{version_num + 1}"
        except:
            return "v1"

    def _record_version_change(
        self,
        kb_name: str,
        filename: str,
        old_version: str,
        new_version: str,
        reason: str
    ):
        """
        记录版本变更到数据库

        Args:
            kb_name: 知识库名称
            filename: 文件名
            old_version: 旧版本号
            new_version: 新版本号
            reason: 变更原因
        """
        try:
            from knowledge.document_versions import get_version_query
            version_query = get_version_query()
            version_query.log_version_change(
                collection=kb_name,
                document_id=filename,
                change_type="update",
                old_version=old_version,
                new_version=new_version,
                old_status="active",
                new_status="active",
                reason=reason,
                changed_by="sync_service"
            )
        except Exception as e:
            logger.warning(f"记录版本变更失败: {e}")

    def sync_now(self) -> SyncResult:
        """立即执行同步"""
        logger.info("开始同步...")

        result = SyncResult(
            status=SyncStatus.RUNNING,
            start_time=datetime.now(),
            end_time=None,
            documents_processed=0,
            documents_added=0,
            documents_modified=0,
            documents_deleted=0,
            errors=[]
        )

        try:
            # 检测变更
            changes = self.detect_changes()

            # 处理变更
            for change in changes:
                success = self.process_change(change)
                result.documents_processed += 1

                if success:
                    if change.change_type == ChangeType.ADDED:
                        result.documents_added += 1
                    elif change.change_type == ChangeType.MODIFIED:
                        result.documents_modified += 1
                    elif change.change_type == ChangeType.DELETED:
                        result.documents_deleted += 1
                else:
                    result.errors.append(f"处理失败: {change.document_id}")

                # 记录变更
                self.db.log_change(change)

            result.status = SyncStatus.COMPLETED

        except Exception as e:
            result.status = SyncStatus.FAILED
            result.errors.append(str(e))
            logger.error(f"同步失败: {e}")

        result.end_time = datetime.now()

        # 记录同步状态
        self.db.log_sync_status(result)

        # 触发回调
        if self.on_sync_callback:
            self.on_sync_callback(result)

        logger.info(f"同步完成: 处理 {result.documents_processed} 个文档, "
                   f"新增 {result.documents_added}, "
                   f"修改 {result.documents_modified}, "
                   f"删除 {result.documents_deleted}")

        return result

    def start(self):
        """启动文件监控"""
        if not HAS_WATCHDOG:
            logger.error("watchdog 未安装，无法启动文件监控")
            return False

        if self._running:
            logger.warning("文件监控已在运行")
            return True

        # 首次同步
        logger.info("执行首次同步...")
        self.sync_now()

        # 启动监控
        event_handler = FileChangeHandler(self)
        self._observer = Observer()
        self._observer.schedule(event_handler, self.documents_path, recursive=True)
        self._observer.start()

        self._running = True
        logger.info(f"文件监控已启动，监控目录: {self.documents_path}")
        return True

    def stop(self):
        """停止文件监控"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

        self._running = False
        logger.info("文件监控已停止")

    def is_running(self) -> bool:
        """检查监控是否在运行"""
        return self._running


# 便捷函数
def create_sync_service(documents_path: str = None) -> KnowledgeSyncService:
    """创建同步服务实例"""
    return KnowledgeSyncService(documents_path)


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("知识库同步服务测试")
    print("=" * 60)

    # 创建服务
    sync_service = KnowledgeSyncService()

    # 测试扫描文档
    print("\n[1] 扫描文档...")
    docs = sync_service.scan_documents()
    print(f"找到 {len(docs)} 个文档")
    for doc_id, doc in list(docs.items())[:5]:
        print(f"  - {doc['document_name']}: {doc['content_hash'][:8]}...")

    # 测试变更检测
    print("\n[2] 检测变更...")
    changes = sync_service.detect_changes()
    print(f"检测到 {len(changes)} 个变更")
    for change in changes[:5]:
        print(f"  - {change.document_name}: {change.change_type.value}")

    # 测试同步
    print("\n[3] 执行同步...")
    result = sync_service.sync_now()
    print(f"同步状态: {result.status.value}")
    print(f"处理文档: {result.documents_processed}")
    print(f"新增: {result.documents_added}, 修改: {result.documents_modified}, 删除: {result.documents_deleted}")

    print("\n" + "=" * 60)
    print("测试完成")
