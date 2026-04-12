"""
知识库同步服务 - 自动检测文档变更并触发增量更新

功能：
1. 文件变更监控 - 使用 watchdog 监控 documents 目录
2. 哈希比对 - 识别文件具体变更类型（新增/修改/删除）
3. 增量向量化 - 仅处理变更文件
4. 变更日志 - 记录变更历史
5. 用户订阅 - 支持订阅特定文档
6. 推送通知 - 变更时通知订阅用户

使用方式：
    from knowledge_sync import KnowledgeSyncService

    # 启动同步服务
    sync_service = KnowledgeSyncService()
    sync_service.start()  # 启动后台监控

    # 手动触发同步
    result = sync_service.sync_now()

    # 订阅文档
    sync_service.subscribe(user_id="user1", document_id="xxx")
"""

import os
import sys
import json
import hashlib
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import logging

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

    def __init__(self, db_path: str = "./data/sync_data.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 文档哈希表 - 记录每个文档的当前哈希
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_hashes (
                document_id TEXT PRIMARY KEY,
                document_name TEXT,
                content_hash TEXT,
                file_size INTEGER,
                last_modified TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 变更日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS change_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT,
                document_name TEXT,
                change_type TEXT,
                old_hash TEXT,
                new_hash TEXT,
                change_time TIMESTAMP,
                processed INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 用户订阅表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                document_id TEXT,
                document_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, document_id)
            )
        ''')

        # 通知记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                document_id TEXT,
                document_name TEXT,
                change_type TEXT,
                message TEXT,
                read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 同步状态表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_type TEXT,
                status TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                documents_processed INTEGER,
                documents_added INTEGER,
                documents_modified INTEGER,
                documents_deleted INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_logs_time ON change_logs(change_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_logs_processed ON change_logs(processed)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read)')

        conn.commit()
        conn.close()

    def get_document_hash(self, document_id: str) -> Optional[Dict]:
        """获取文档的当前哈希"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT document_id, document_name, content_hash, file_size, last_modified
            FROM document_hashes WHERE document_id = ?
        ''', (document_id,))
        row = cursor.fetchone()
        conn.close()

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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO document_hashes
            (document_id, document_name, content_hash, file_size, last_modified, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (document_id, document_name, content_hash, file_size, last_modified))
        conn.commit()
        conn.close()

    def delete_document_hash(self, document_id: str):
        """删除文档哈希记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM document_hashes WHERE document_id = ?', (document_id,))
        conn.commit()
        conn.close()

    def get_all_document_hashes(self) -> Dict[str, Dict]:
        """获取所有文档哈希"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT document_id, document_name, content_hash, file_size, last_modified
            FROM document_hashes
        ''')
        rows = cursor.fetchall()
        conn.close()

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
        conn = sqlite3.connect(self.db_path)
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
        change_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return change_id

    def get_change_logs(self, limit: int = 100, processed: Optional[bool] = None,
                        days: int = 30) -> List[Dict]:
        """获取变更日志"""
        conn = sqlite3.connect(self.db_path)
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
        conn.close()

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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE change_logs
            SET processed = 1, error_message = ?
            WHERE id = ?
        ''', (error_message, change_id))
        conn.commit()
        conn.close()

    def subscribe(self, user_id: str, document_id: str = None, document_name: str = None):
        """用户订阅文档"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO subscriptions (user_id, document_id, document_name)
                VALUES (?, ?, ?)
            ''', (user_id, document_id, document_name))
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # 已存在
        finally:
            conn.close()

    def unsubscribe(self, user_id: str, document_id: str = None):
        """取消订阅"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if document_id:
            cursor.execute('''
                DELETE FROM subscriptions WHERE user_id = ? AND document_id = ?
            ''', (user_id, document_id))
        else:
            cursor.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    def get_subscribers(self, document_id: str) -> List[str]:
        """获取订阅某文档的用户"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id FROM subscriptions
            WHERE document_id = ? OR document_id IS NULL
        ''', (document_id,))
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    def add_notification(self, user_id: str, document_id: str, document_name: str,
                         change_type: str, message: str):
        """添加通知"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notifications (user_id, document_id, document_name, change_type, message)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, document_id, document_name, change_type, message))
        conn.commit()
        conn.close()

    def get_notifications(self, user_id: str, unread_only: bool = False) -> List[Dict]:
        """获取用户通知"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        sql = '''
            SELECT id, document_id, document_name, change_type, message, read, created_at
            FROM notifications WHERE user_id = ?
        '''
        params = [user_id]

        if unread_only:
            sql += ' AND read = 0'

        sql += ' ORDER BY created_at DESC LIMIT 50'

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row[0],
                "document_id": row[1],
                "document_name": row[2],
                "change_type": row[3],
                "message": row[4],
                "read": bool(row[5]),
                "created_at": row[6]
            }
            for row in rows
        ]

    def mark_notification_read(self, notification_id: int):
        """标记通知已读"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE notifications SET read = 1 WHERE id = ?', (notification_id,))
        conn.commit()
        conn.close()

    def log_sync_status(self, result: SyncResult) -> int:
        """记录同步状态"""
        conn = sqlite3.connect(self.db_path)
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
        sync_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return sync_id

    def get_sync_history(self, limit: int = 20) -> List[Dict]:
        """获取同步历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, sync_type, status, start_time, end_time,
                   documents_processed, documents_added, documents_modified, documents_deleted, error_message
            FROM sync_status
            ORDER BY start_time DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()

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
        self.supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}
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

    def __init__(self, documents_path: str = None, db_path: str = "./data/sync_data.db"):
        """
        初始化同步服务

        Args:
            documents_path: 文档目录路径，默认为 ./documents
            db_path: 数据库路径
        """
        self.documents_path = documents_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "documents"
        )
        self.db = SyncDatabase(db_path)

        self._observer = None
        self._running = False
        self.on_change_callback: Optional[Callable] = None
        self.on_sync_callback: Optional[Callable] = None

        # 导入 RAG 组件（延迟导入避免循环依赖）
        self._rag_module = None

    def _get_rag_module(self):
        """延迟加载 RAG 模块"""
        if self._rag_module is None:
            try:
                from rag_demo import (
                    add_file_to_index,
                    delete_file_from_index,
                    rebuild_bm25_index,
                    BM25_INDEX_PATH,
                    bm25_index
                )
                self._rag_module = {
                    'add_file_to_index': add_file_to_index,
                    'delete_file_from_index': delete_file_from_index,
                    'rebuild_bm25_index': rebuild_bm25_index,
                    'BM25_INDEX_PATH': BM25_INDEX_PATH,
                    'bm25_index': bm25_index
                }
            except ImportError as e:
                logger.error(f"无法导入 RAG 模块: {e}")
        return self._rag_module

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
        supported_extensions = {'.pdf', '.docx', '.doc', '.xlsx', '.txt'}

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
            from knowledge_base_manager import get_kb_manager
            kb_manager = get_kb_manager()

            if change.change_type == ChangeType.ADDED:
                # 新增文档 - 使用多向量库方法
                chunks_added = kb_manager.add_file_to_kb(
                    kb_name=kb_name,
                    filepath=file_path,
                    extra_metadata={'status': 'active', 'version': 'v1'}
                )
                # 更新哈希记录
                self.db.set_document_hash(
                    change.document_id,
                    change.document_name,
                    change.new_hash,
                    os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    datetime.now()
                )
                logger.info(f"已添加文档到 {kb_name}: {change.document_id}, 片段数: {chunks_added}")

            elif change.change_type == ChangeType.MODIFIED:
                # 修改文档：先删除旧索引，再添加新索引
                deleted = kb_manager.delete_document(kb_name, change.document_name)
                chunks_added = kb_manager.add_file_to_kb(
                    kb_name=kb_name,
                    filepath=file_path,
                    extra_metadata={'status': 'active', 'version': 'v1'}
                )
                # 更新哈希记录
                self.db.set_document_hash(
                    change.document_id,
                    change.document_name,
                    change.new_hash,
                    os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    datetime.now()
                )
                logger.info(f"已更新文档: {change.document_id}, 删除 {deleted} 片段, 添加 {chunks_added} 片段")

            elif change.change_type == ChangeType.DELETED:
                # 删除文档
                deleted = kb_manager.delete_document(kb_name, change.document_name)
                # 删除哈希记录
                self.db.delete_document_hash(change.document_id)
                logger.info(f"已删除文档: {change.document_id}, 删除 {deleted} 片段")

            # 发送通知
            self._send_notifications(change)

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
            document_id: 文档ID，格式如 "public/filename.pdf" 或 "finance/filename.pdf"

        Returns:
            向量库名称，如 "public_kb" 或 "dept_finance"
        """
        # 获取第一级目录名
        parts = document_id.split('/')
        if len(parts) > 1:
            subdir = parts[0]
        else:
            subdir = 'public'

        # 映射到向量库名称
        if subdir == 'public':
            return 'public_kb'
        else:
            return f'dept_{subdir}'

    def _send_notifications(self, change: DocumentChange):
        """发送变更通知"""
        # 获取订阅用户
        subscribers = self.db.get_subscribers(change.document_id)

        # 构建通知消息
        change_type_names = {
            ChangeType.ADDED: "新增",
            ChangeType.MODIFIED: "更新",
            ChangeType.DELETED: "删除"
        }

        message = f"文档「{change.document_name}」已{change_type_names[change.change_type]}"

        # 添加通知
        for user_id in subscribers:
            self.db.add_notification(
                user_id=user_id,
                document_id=change.document_id,
                document_name=change.document_name,
                change_type=change.change_type.value,
                message=message
            )
            logger.info(f"已通知用户 {user_id}: {message}")

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
def create_sync_service(documents_path: str = None, db_path: str = "./data/sync_data.db") -> KnowledgeSyncService:
    """创建同步服务实例"""
    return KnowledgeSyncService(documents_path, db_path)


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

    # 测试订阅
    print("\n[4] 测试订阅...")
    if docs:
        first_doc = list(docs.keys())[0]
        sync_service.db.subscribe("test_user", first_doc, docs[first_doc]["document_name"])
        subscribers = sync_service.db.get_subscribers(first_doc)
        print(f"订阅 '{first_doc}' 的用户: {subscribers}")

    # 测试通知
    print("\n[5] 测试通知...")
    notifications = sync_service.db.get_notifications("test_user", unread_only=True)
    print(f"用户 test_user 的未读通知: {len(notifications)}")

    print("\n" + "=" * 60)
    print("测试完成")
