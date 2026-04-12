"""
多向量库管理器 - 支持按部门/权限隔离的向量知识库

功能：
1. 多向量库管理 - 创建、删除、列举向量库
2. 多 BM25 索引管理 - 每个向量库独立的 BM25 索引
3. 权限过滤 - 根据用户角色和部门返回可访问的向量库
4. 并行检索 - 支持同时检索多个向量库

向量库命名规范：
- public_kb: 公开知识库，所有人可访问
- dept_{部门名}: 部门知识库，如 dept_finance, dept_hr, dept_tech

使用方式：
    from knowledge_base_manager import KnowledgeBaseManager

    kb_manager = KnowledgeBaseManager()

    # 获取向量库
    collection = kb_manager.get_collection("dept_finance")

    # 列出所有向量库
    collections = kb_manager.list_collections()

    # 获取用户可访问的向量库
    accessible = kb_manager.get_accessible_collections("manager", "finance")
"""

import os
import json
import pickle
import threading
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

import chromadb
from chromadb import Collection
import numpy as np
from rank_bm25 import BM25Okapi
import jieba

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 配置常量 ====================

# 向量存储基础路径
VECTOR_STORE_BASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "vector_store"
)

# 向量库基础路径
CHROMA_DB_BASE_PATH = os.path.join(VECTOR_STORE_BASE_PATH, "chroma")

# BM25 索引基础路径
BM25_INDEX_BASE_PATH = os.path.join(VECTOR_STORE_BASE_PATH, "bm25")

# 向量库元数据文件
KB_METADATA_FILE = "kb_metadata.json"

# 预定义的公开知识库名称
PUBLIC_KB_NAME = "public_kb"

# 默认部门列表（可根据实际情况扩展）
DEFAULT_DEPARTMENTS = ["finance", "hr", "tech", "operation", "marketing"]


# ==================== 数据结构 ====================

@dataclass
class CollectionInfo:
    """向量库信息"""
    name: str                          # 向量库名称
    display_name: str                  # 显示名称
    document_count: int = 0            # 文档数量
    created_at: str = ""               # 创建时间
    department: str = ""               # 所属部门（空表示公开库）
    description: str = ""              # 描述


@dataclass
class SearchResult:
    """检索结果"""
    ids: List[str]
    documents: List[str]
    metadatas: List[dict]
    distances: List[float]
    collection_name: str = ""


# ==================== BM25 索引管理 ====================

class BM25Index:
    """BM25 索引"""

    def __init__(self):
        self.bm25: Optional[BM25Okapi] = None
        self.ids: List[str] = []
        self.documents: List[str] = []
        self.metadatas: List[dict] = []

    def tokenize(self, text: str) -> List[str]:
        """中文分词"""
        return list(jieba.cut(text))

    def add_documents(self, ids: List[str], documents: List[str], metadatas: List[dict]):
        """添加文档"""
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas

        if documents:
            tokenized = [self.tokenize(doc) for doc in documents]
            self.bm25 = BM25Okapi(tokenized)

    def search(self, query: str, top_k: int = 10) -> Tuple[List[str], List[str], List[dict], List[float]]:
        """搜索"""
        if not self.bm25 or not self.documents:
            return [], [], [], []

        tokenized_query = self.tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        # 获取 top_k 结果
        top_indices = np.argsort(scores)[::-1][:top_k]

        return (
            [self.ids[i] for i in top_indices],
            [self.documents[i] for i in top_indices],
            [self.metadatas[i] for i in top_indices],
            [float(scores[i]) for i in top_indices]
        )

    def save(self, filepath: str):
        """保存索引"""
        data = {
            'ids': self.ids,
            'documents': self.documents,
            'metadatas': self.metadatas
        }
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'wb') as f:
            pickle.dump(data, f)

    def load(self, filepath: str) -> bool:
        """加载索引"""
        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'rb') as f:
                data = pickle.load(f)

            self.ids = data.get('ids', [])
            self.documents = data.get('documents', [])
            self.metadatas = data.get('metadatas', [])

            if self.documents:
                tokenized = [self.tokenize(doc) for doc in self.documents]
                self.bm25 = BM25Okapi(tokenized)

            return True
        except Exception as e:
            logger.error(f"加载 BM25 索引失败: {e}")
            return False

    def clear(self):
        """清空索引"""
        self.bm25 = None
        self.ids = []
        self.documents = []
        self.metadatas = []


# ==================== 多向量库管理器 ====================

class KnowledgeBaseManager:
    """
    多向量库管理器

    管理多个独立的 ChromaDB 集合，每个集合对应一个知识库。
    支持按部门隔离，每个部门有独立的向量库和 BM25 索引。
    """

    def __init__(self, base_path: str = None, bm25_base_path: str = None):
        """
        初始化

        Args:
            base_path: 向量库存储路径
            bm25_base_path: BM25 索引存储路径
        """
        self.base_path = base_path or CHROMA_DB_BASE_PATH
        self.bm25_base_path = bm25_base_path or BM25_INDEX_BASE_PATH

        # 缓存
        self._collections: Dict[str, Collection] = {}
        self._bm25_indexes: Dict[str, BM25Index] = {}
        self._clients: Dict[str, chromadb.PersistentClient] = {}
        self._lock = threading.Lock()

        # 确保目录存在
        os.makedirs(self.base_path, exist_ok=True)
        os.makedirs(self.bm25_base_path, exist_ok=True)

        # 加载元数据
        self._metadata = self._load_metadata()

        # 初始化公开知识库
        self._ensure_public_kb()

        logger.info(f"知识库管理器初始化完成，路径: {self.base_path}")

    def _load_metadata(self) -> dict:
        """加载元数据"""
        metadata_path = os.path.join(self.base_path, KB_METADATA_FILE)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载元数据失败: {e}")
        return {"collections": {}}

    def _save_metadata(self):
        """保存元数据"""
        metadata_path = os.path.join(self.base_path, KB_METADATA_FILE)
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")

    def _ensure_public_kb(self):
        """确保公开知识库存在"""
        if PUBLIC_KB_NAME not in self._metadata.get("collections", {}):
            self.create_collection(
                PUBLIC_KB_NAME,
                display_name="公开知识库",
                department="",
                description="所有人可访问的公开文档"
            )

    def _get_client(self, kb_name: str) -> chromadb.PersistentClient:
        """获取或创建 ChromaDB 客户端"""
        if kb_name not in self._clients:
            db_path = os.path.join(self.base_path, kb_name)
            os.makedirs(db_path, exist_ok=True)
            self._clients[kb_name] = chromadb.PersistentClient(path=db_path)
        return self._clients[kb_name]

    # ==================== 向量库管理 ====================

    def get_collection(self, kb_name: str) -> Optional[Collection]:
        """
        获取或创建向量库集合

        Args:
            kb_name: 向量库名称

        Returns:
            ChromaDB Collection 对象
        """
        with self._lock:
            if kb_name in self._collections:
                return self._collections[kb_name]

            try:
                client = self._get_client(kb_name)
                # 必须增加 hnsw:sync_threshold 以防止 Windows 上一次性大批量密集写入时报错索引损坏
                collection = client.get_or_create_collection(
                    name=kb_name,
                    metadata={
                        "hnsw:space": "cosine",
                        "hnsw:sync_threshold": 100000 
                    }
                )
                self._collections[kb_name] = collection
                logger.info(f"获取向量库: {kb_name}, 文档数: {collection.count()}")
                return collection
            except Exception as e:
                logger.error(f"获取向量库失败: {kb_name}, 错误: {e}")
                return None

    def create_collection(
        self,
        kb_name: str,
        display_name: str = "",
        department: str = "",
        description: str = ""
    ) -> Tuple[bool, str]:
        """
        创建新向量库

        Args:
            kb_name: 向量库名称
            display_name: 显示名称
            department: 所属部门
            description: 描述

        Returns:
            (success, message)
        """
        from datetime import datetime

        # 验证名称
        if not kb_name or not kb_name.replace('_', '').isalnum():
            return False, "向量库名称只能包含字母、数字和下划线"

        # 检查是否已存在
        if kb_name in self._metadata.get("collections", {}):
            return False, f"向量库 '{kb_name}' 已存在"

        try:
            # 创建集合
            collection = self.get_collection(kb_name)
            if not collection:
                return False, "创建向量库失败"

            # 创建 BM25 索引
            self._bm25_indexes[kb_name] = BM25Index()

            # 更新元数据
            if "collections" not in self._metadata:
                self._metadata["collections"] = {}

            self._metadata["collections"][kb_name] = {
                "display_name": display_name or kb_name,
                "department": department,
                "description": description,
                "created_at": datetime.now().isoformat()
            }
            self._save_metadata()

            logger.info(f"创建向量库: {kb_name}")
            return True, f"向量库 '{kb_name}' 创建成功"

        except Exception as e:
            logger.error(f"创建向量库失败: {e}")
            return False, f"创建失败: {str(e)}"

    def delete_collection(self, kb_name: str) -> Tuple[bool, str]:
        """
        删除向量库

        Args:
            kb_name: 向量库名称

        Returns:
            (success, message)
        """
        # 保护公开知识库
        if kb_name == PUBLIC_KB_NAME:
            return False, "公开知识库不能删除"

        # 检查是否存在
        if kb_name not in self._metadata.get("collections", {}):
            return False, f"向量库 '{kb_name}' 不存在"

        try:
            # 删除集合
            client = self._get_client(kb_name)
            client.delete_collection(kb_name)

            # 清理缓存
            if kb_name in self._collections:
                del self._collections[kb_name]
            if kb_name in self._bm25_indexes:
                del self._bm25_indexes[kb_name]
            if kb_name in self._clients:
                del self._clients[kb_name]

            # 删除 BM25 索引文件
            bm25_path = os.path.join(self.bm25_base_path, f"{kb_name}.pkl")
            if os.path.exists(bm25_path):
                os.remove(bm25_path)

            # 更新元数据
            if kb_name in self._metadata.get("collections", {}):
                del self._metadata["collections"][kb_name]
            self._save_metadata()

            logger.info(f"删除向量库: {kb_name}")
            return True, f"向量库 '{kb_name}' 已删除"

        except Exception as e:
            logger.error(f"删除向量库失败: {e}")
            return False, f"删除失败: {str(e)}"

    def list_collections(self) -> List[CollectionInfo]:
        """
        列出所有向量库

        Returns:
            向量库信息列表
        """
        result = []

        # 从元数据获取
        for name, info in self._metadata.get("collections", {}).items():
            collection = self.get_collection(name)
            result.append(CollectionInfo(
                name=name,
                display_name=info.get("display_name", name),
                document_count=collection.count() if collection else 0,
                created_at=info.get("created_at", ""),
                department=info.get("department", ""),
                description=info.get("description", "")
            ))

        return result

    def collection_exists(self, kb_name: str) -> bool:
        """检查向量库是否存在"""
        return kb_name in self._metadata.get("collections", {})

    # ==================== BM25 索引管理 ====================

    def get_bm25_index(self, kb_name: str) -> BM25Index:
        """
        获取或加载 BM25 索引

        Args:
            kb_name: 向量库名称

        Returns:
            BM25Index 对象
        """
        if kb_name not in self._bm25_indexes:
            self._bm25_indexes[kb_name] = BM25Index()

            # 尝试加载
            bm25_path = os.path.join(self.bm25_base_path, f"{kb_name}.pkl")
            if os.path.exists(bm25_path):
                self._bm25_indexes[kb_name].load(bm25_path)

        return self._bm25_indexes[kb_name]

    def save_bm25_index(self, kb_name: str):
        """保存 BM25 索引"""
        if kb_name in self._bm25_indexes:
            bm25_path = os.path.join(self.bm25_base_path, f"{kb_name}.pkl")
            self._bm25_indexes[kb_name].save(bm25_path)
            logger.info(f"保存 BM25 索引: {kb_name}")

    def rebuild_bm25_index(self, kb_name: str) -> bool:
        """
        重建 BM25 索引

        Args:
            kb_name: 向量库名称

        Returns:
            是否成功
        """
        try:
            collection = self.get_collection(kb_name)
            if not collection:
                return False

            # 获取所有文档
            result = collection.get()

            # 创建新索引
            bm25_index = BM25Index()
            if result['ids']:
                bm25_index.add_documents(
                    ids=result['ids'],
                    documents=result['documents'],
                    metadatas=result['metadatas']
                )

            # 保存
            self._bm25_indexes[kb_name] = bm25_index
            self.save_bm25_index(kb_name)

            logger.info(f"重建 BM25 索引: {kb_name}, 文档数: {len(result['ids'])}")
            return True

        except Exception as e:
            logger.error(f"重建 BM25 索引失败: {e}")
            return False

    # ==================== 权限管理 ====================

    def get_accessible_collections(
        self,
        role: str,
        department: str,
        operation: str = "read"
    ) -> List[str]:
        """
        获取用户可访问的向量库列表

        Args:
            role: 用户角色 (admin/manager/user)
            department: 用户部门
            operation: 操作类型 (read/write/delete/sync)

        Returns:
            可访问的向量库名称列表
        """
        result = []

        # admin 可以访问所有
        if role == "admin":
            for info in self.list_collections():
                result.append(info.name)
            return result

        # manager 和 user 可以访问 public 和本部门
        if PUBLIC_KB_NAME in self._metadata.get("collections", {}):
            result.append(PUBLIC_KB_NAME)

        # 本部门向量库
        if department:
            dept_kb = f"dept_{department}"
            if dept_kb in self._metadata.get("collections", {}):
                # 检查操作权限
                if operation == "read":
                    result.append(dept_kb)
                elif operation in ("write", "delete", "sync"):
                    # 只有 manager 可以对本部门进行写操作
                    if role == "manager":
                        result.append(dept_kb)

        return result

    def check_permission(
        self,
        role: str,
        department: str,
        kb_name: str,
        operation: str = "read"
    ) -> bool:
        """
        检查用户对向量库的操作权限

        Args:
            role: 用户角色
            department: 用户部门
            kb_name: 向量库名称
            operation: 操作类型 (read/write/delete/sync)

        Returns:
            是否有权限
        """
        accessible = self.get_accessible_collections(role, department, operation)
        return kb_name in accessible

    # ==================== 文档操作 ====================

    def get_document_count(self, kb_name: str) -> int:
        """获取向量库中的文档数量"""
        collection = self.get_collection(kb_name)
        return collection.count() if collection else 0

    def list_documents(self, kb_name: str) -> List[dict]:
        """
        列出向量库中的文档

        Args:
            kb_name: 向量库名称

        Returns:
            文档信息列表
        """
        collection = self.get_collection(kb_name)
        if not collection:
            return []

        result = collection.get()

        # 按文件名分组
        from collections import Counter
        file_chunks = Counter()

        for meta in result.get('metadatas', []):
            source = meta.get('source', 'unknown')
            file_chunks[source] += 1

        return [
            {"source": source, "chunks": count}
            for source, count in file_chunks.items()
        ]

    def delete_document(self, kb_name: str, filename: str) -> int:
        """
        从向量库删除文档

        Args:
            kb_name: 向量库名称
            filename: 文件名

        Returns:
            删除的片段数
        """
        collection = self.get_collection(kb_name)
        if not collection:
            return 0

        # 查询该文件的所有片段
        result = collection.get(where={"source": filename})

        if not result['ids']:
            return 0

        # 删除
        collection.delete(ids=result['ids'])
        deleted = len(result['ids'])

        logger.info(f"从 {kb_name} 删除文档: {filename}, 片段数: {deleted}")

        return deleted

    def add_file_to_kb(
        self,
        kb_name: str,
        filepath: str,
        embedding_model=None,
        extra_metadata: dict = None
    ) -> int:
        """
        添加文件到指定向量库

        Args:
            kb_name: 向量库名称
            filepath: 文件绝对路径
            embedding_model: 向量模型（可选，默认使用 rag_demo 的）
            extra_metadata: 额外的元数据（如 status, version 等）

        Returns:
            添加的片段数量
        """
        collection = self.get_collection(kb_name)
        if not collection:
            logger.error(f"向量库不存在: {kb_name}")
            return 0

        # 获取向量模型
        if embedding_model is None:
            try:
                from rag_demo import embedding_model as emb
                embedding_model = emb
            except ImportError:
                logger.error("无法加载向量模型")
                return 0

        ext = os.path.splitext(filepath)[1].lower()
        supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx'}

        if ext not in supported_extensions:
            logger.warning(f"不支持的文件格式: {ext}")
            return 0

        # 获取文件相对路径（作为 source）
        filename = os.path.basename(filepath)
        extra_metadata = extra_metadata or {}

        total_chunks = 0

        try:
            if ext == '.pdf':
                total_chunks = self._add_pdf_to_collection(
                    collection, filepath, filename, embedding_model, extra_metadata
                )
            elif ext == '.docx':
                total_chunks = self._add_docx_to_collection(
                    collection, filepath, filename, embedding_model, extra_metadata
                )
            elif ext == '.xlsx':
                total_chunks = self._add_xlsx_to_collection(
                    collection, filepath, filename, embedding_model, extra_metadata
                )
            elif ext == '.txt':
                total_chunks = self._add_txt_to_collection(
                    collection, filepath, filename, embedding_model, extra_metadata
                )

            # 重建 BM25 索引
            if total_chunks > 0:
                self._rebuild_bm25_index(kb_name)

            logger.info(f"添加文件到 {kb_name}: {filename}, 片段数: {total_chunks}")

        except Exception as e:
            logger.error(f"添加文件失败: {filepath}, 错误: {e}")

        return total_chunks

    def _add_pdf_to_collection(self, collection, filepath, filename, embedding_model, extra_metadata):
        """添加 PDF 文件"""
        try:
            from rag_demo import extract_text_from_pdf, split_text
        except ImportError:
            logger.error("无法导入 PDF 处理函数")
            return 0

        total_chunks = 0
        pages = extract_text_from_pdf(filepath)

        if pages:
            for page_info in pages:
                page_text = page_info['text']
                page_num = page_info['page']
                has_table = page_info.get('has_table', False)
                section = page_info.get('section', '')

                chunks = split_text(page_text)

                for i, chunk in enumerate(chunks):
                    vector = embedding_model.encode(chunk).tolist()
                    chunk_id = f"{filename}_p{page_num}_{i}_{total_chunks}"

                    metadata = {
                        'source': filename,
                        'page': page_num,
                        'chunk_index': i,
                        'has_table': has_table,
                        'section': section,
                        'collection': collection.name,
                        **extra_metadata
                    }

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[metadata]
                    )
                    total_chunks += 1

            logger.info(f"添加 {filename}: {total_chunks} 个片段 (PDF, {len(pages)}页)")

        return total_chunks

    def _add_docx_to_collection(self, collection, filepath, filename, embedding_model, extra_metadata):
        """添加 DOCX 文件"""
        try:
            from rag_demo import extract_text_from_docx, split_text
        except ImportError:
            logger.error("无法导入 DOCX 处理函数")
            return 0

        total_chunks = 0
        blocks = extract_text_from_docx(filepath)

        if blocks:
            for block in blocks:
                text = block['text']
                if len(text.strip()) < 10:
                    continue

                is_table = block.get('is_table', False)
                section = block.get('section', '')

                chunks = [text] if is_table else split_text(text)

                for i, chunk in enumerate(chunks):
                    vector = embedding_model.encode(chunk).tolist()
                    chunk_id = f"{filename}_{total_chunks}_{i}"

                    metadata = {
                        'source': filename,
                        'chunk_index': total_chunks,
                        'is_table': is_table,
                        'section': section,
                        'collection': collection.name,
                        **extra_metadata
                    }

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[metadata]
                    )
                    total_chunks += 1

            tables_count = sum(1 for b in blocks if b.get('is_table'))
            logger.info(f"添加 {filename}: {total_chunks} 个片段 (Word, {len(blocks)}段落)")

        return total_chunks

    def _add_xlsx_to_collection(self, collection, filepath, filename, embedding_model, extra_metadata):
        """添加 XLSX 文件"""
        try:
            from rag_demo import extract_text_from_xlsx
        except ImportError:
            logger.error("无法导入 XLSX 处理函数")
            return 0

        total_chunks = 0
        rows = extract_text_from_xlsx(filepath)

        if rows:
            for row_info in rows:
                text = row_info['text']
                if len(text.strip()) < 5:
                    continue

                sheet = row_info['sheet']
                row_num = row_info['row']
                is_header = row_info.get('is_header', False)
                header = row_info.get('header', '')

                full_text = text
                if header and not is_header:
                    full_text = f"【表头: {header}】\n{text}"

                vector = embedding_model.encode(full_text).tolist()
                chunk_id = f"{filename}_{sheet}_{row_num}"

                metadata = {
                    'source': filename,
                    'sheet': sheet,
                    'row': row_num,
                    'is_header': is_header,
                    'collection': collection.name,
                    **extra_metadata
                }

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[full_text],
                    metadatas=[metadata]
                )
                total_chunks += 1

            sheets = set(r['sheet'] for r in rows)
            logger.info(f"添加 {filename}: {total_chunks} 个片段 (Excel, {len(sheets)}工作表)")

        return total_chunks

    def _add_txt_to_collection(self, collection, filepath, filename, embedding_model, extra_metadata):
        """添加 TXT 文件"""
        try:
            from rag_demo import extract_text_from_txt, split_text
        except ImportError:
            logger.error("无法导入 TXT 处理函数")
            return 0

        total_chunks = 0
        content = extract_text_from_txt(filepath)

        if content.strip():
            chunks = split_text(content)
            for i, chunk in enumerate(chunks):
                vector = embedding_model.encode(chunk).tolist()
                chunk_id = f"{filename}_{i}"

                metadata = {
                    'source': filename,
                    'chunk_index': i,
                    'collection': collection.name,
                    **extra_metadata
                }

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[chunk],
                    metadatas=[metadata]
                )
                total_chunks += 1

            logger.info(f"添加 {filename}: {total_chunks} 个片段 (TXT)")

        return total_chunks

    def _rebuild_bm25_index(self, kb_name: str):
        """重建指定向量库的 BM25 索引"""
        collection = self.get_collection(kb_name)
        if not collection:
            return

        result = collection.get()

        if result['ids']:
            bm25_index = BM25Index()
            bm25_index.add_documents(
                ids=result['ids'],
                documents=result['documents'],
                metadatas=result['metadatas']
            )

            # 保存索引
            index_path = os.path.join(BM25_INDEX_BASE_PATH, f"{kb_name}_bm25.pkl")
            bm25_index.save(index_path)

            # 更新缓存
            self._bm25_indexes[kb_name] = bm25_index

            logger.info(f"重建 BM25 索引: {kb_name}, 文档数: {len(result['ids'])}")

    # ==================== 检索功能 ====================

    def search_single(
        self,
        kb_name: str,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        use_bm25: bool = True
    ) -> Optional[SearchResult]:
        """
        单向量库检索

        Args:
            kb_name: 向量库名称
            query_vector: 查询向量
            query_text: 查询文本（用于 BM25）
            top_k: 返回数量
            use_bm25: 是否使用 BM25

        Returns:
            检索结果
        """
        collection = self.get_collection(kb_name)
        if not collection or collection.count() == 0:
            return None

        # 向量检索
        vector_result = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k
        )

        if not use_bm25:
            return SearchResult(
                ids=vector_result['ids'][0],
                documents=vector_result['documents'][0],
                metadatas=vector_result['metadatas'][0],
                distances=vector_result['distances'][0],
                collection_name=kb_name
            )

        # BM25 检索
        bm25_index = self.get_bm25_index(kb_name)
        bm25_ids, bm25_docs, bm25_metas, bm25_scores = bm25_index.search(
            query_text, top_k=min(top_k * 2, 20)
        )

        # RRF 融合
        return self._merge_results(
            vector_result,
            (bm25_ids, bm25_docs, bm25_metas, bm25_scores),
            top_k=top_k,
            collection_name=kb_name
        )

    def search_multiple(
        self,
        kb_names: List[str],
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        use_bm25: bool = True
    ) -> SearchResult:
        """
        多向量库并行检索

        Args:
            kb_names: 向量库名称列表
            query_vector: 查询向量
            query_text: 查询文本
            top_k: 每个库返回数量
            use_bm25: 是否使用 BM25

        Returns:
            合并后的检索结果
        """
        if not kb_names:
            return SearchResult(
                ids=[], documents=[], metadatas=[], distances=[]
            )

        # 并行检索
        results = []
        with ThreadPoolExecutor(max_workers=len(kb_names)) as executor:
            futures = {
                executor.submit(
                    self.search_single,
                    kb_name,
                    query_vector,
                    query_text,
                    top_k,
                    use_bm25
                ): kb_name for kb_name in kb_names
            }

            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        # 合并结果
        return self._merge_multiple_results(results, top_k)

    def _merge_results(
        self,
        vector_result: dict,
        bm25_result: Tuple,
        top_k: int,
        collection_name: str
    ) -> SearchResult:
        """RRF 融合向量检索和 BM25 检索结果"""
        k = 60  # RRF 参数

        doc_scores = {}

        # 向量检索结果
        for rank, (doc_id, doc, meta, dist) in enumerate(zip(
            vector_result['ids'][0],
            vector_result['documents'][0],
            vector_result['metadatas'][0],
            vector_result['distances'][0]
        )):
            rrf_score = 1 / (k + rank + 1)
            # 距离转换为相似度（cosine 距离）
            sim_score = 1 - dist
            combined = rrf_score * 0.5 + sim_score * 0.5

            doc_scores[doc_id] = {
                'score': combined,
                'doc': doc,
                'meta': meta
            }

        # BM25 结果
        bm25_ids, bm25_docs, bm25_metas, bm25_scores = bm25_result
        for rank, (doc_id, doc, meta, score) in enumerate(zip(
            bm25_ids, bm25_docs, bm25_metas, bm25_scores
        )):
            rrf_score = 1 / (k + rank + 1)
            # BM25 分数归一化
            norm_score = score / 10.0 if score > 0 else 0
            combined = rrf_score * 0.5 + norm_score * 0.5

            if doc_id in doc_scores:
                doc_scores[doc_id]['score'] += combined
            else:
                doc_scores[doc_id] = {
                    'score': combined,
                    'doc': doc,
                    'meta': meta
                }

        # 排序
        sorted_items = sorted(
            doc_scores.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )[:top_k]

        return SearchResult(
            ids=[item[0] for item in sorted_items],
            documents=[item[1]['doc'] for item in sorted_items],
            metadatas=[item[1]['meta'] for item in sorted_items],
            distances=[item[1]['score'] for item in sorted_items],
            collection_name=collection_name
        )

    def _merge_multiple_results(
        self,
        results: List[SearchResult],
        top_k: int
    ) -> SearchResult:
        """合并多个向量库的检索结果"""
        if not results:
            return SearchResult(
                ids=[], documents=[], metadatas=[], distances=[]
            )

        if len(results) == 1:
            return results[0]

        # 收集所有结果
        all_items = []
        for result in results:
            for i, doc_id in enumerate(result.ids):
                all_items.append({
                    'id': doc_id,
                    'doc': result.documents[i],
                    'meta': result.metadatas[i],
                    'score': result.distances[i],
                    'collection': result.collection_name
                })

        # 按分数排序
        all_items.sort(key=lambda x: x['score'], reverse=True)

        # 去重（保留最高分）
        seen = set()
        unique_items = []
        for item in all_items:
            if item['id'] not in seen:
                seen.add(item['id'])
                unique_items.append(item)

        # 取 top_k
        unique_items = unique_items[:top_k]

        return SearchResult(
            ids=[item['id'] for item in unique_items],
            documents=[item['doc'] for item in unique_items],
            metadatas=[item['meta'] for item in unique_items],
            distances=[item['score'] for item in unique_items],
            collection_name="multiple"
        )

    # ==================== 版本管理与软删除 ====================

    def deprecate_document(
        self,
        kb_name: str,
        filename: str,
        reason: str = "制度废止",
        deprecated_by: str = ""
    ) -> Dict:
        """
        软删除文档 - 将chunks状态标记为deprecated

        Args:
            kb_name: 向量库名称
            filename: 文件名
            reason: 废止原因
            deprecated_by: 操作用户

        Returns:
            {
                "success": True,
                "deprecated_chunks": 15,
                "document_id": "xxx.pdf",
                "collection": "dept_finance"
            }
        """
        from datetime import datetime

        collection = self.get_collection(kb_name)
        if not collection:
            return {"success": False, "error": "向量库不存在"}

        # 查询该文件的所有chunks
        result = collection.get(where={"source": filename})

        if not result['ids']:
            return {"success": False, "error": "文档不存在"}

        # 更新元数据（软删除）
        deprecated_date = datetime.now().isoformat()
        updated_metadatas = [
            {
                **m,
                "status": "deprecated",
                "deprecated_date": deprecated_date,
                "deprecated_reason": reason,
                "deprecated_by": deprecated_by
            }
            for m in result['metadatas']
        ]

        collection.update(
            ids=result['ids'],
            metadatas=updated_metadatas
        )

        # 更新BM25索引
        self.rebuild_bm25_index(kb_name)

        logger.info(f"软删除文档: {kb_name}/{filename}, chunks: {len(result['ids'])}, 原因: {reason}")

        return {
            "success": True,
            "deprecated_chunks": len(result['ids']),
            "document_id": filename,
            "collection": kb_name,
            "deprecated_date": deprecated_date
        }

    def restore_document(self, kb_name: str, filename: str) -> Dict:
        """
        恢复已废止的文档

        Args:
            kb_name: 向量库名称
            filename: 文件名

        Returns:
            {
                "success": True,
                "restored_chunks": 15
            }
        """
        collection = self.get_collection(kb_name)
        if not collection:
            return {"success": False, "error": "向量库不存在"}

        # 查询该文件的所有已废止chunks
        result = collection.get(
            where={
                "$and": [
                    {"source": filename},
                    {"status": "deprecated"}
                ]
            }
        )

        if not result['ids']:
            return {"success": False, "error": "未找到已废止的文档"}

        # 恢复元数据
        updated_metadatas = [
            {
                **m,
                "status": "active",
                "deprecated_date": None,
                "deprecated_reason": None
            }
            for m in result['metadatas']
        ]

        collection.update(
            ids=result['ids'],
            metadatas=updated_metadatas
        )

        # 更新BM25索引
        self.rebuild_bm25_index(kb_name)

        logger.info(f"恢复文档: {kb_name}/{filename}, chunks: {len(result['ids'])}")

        return {
            "success": True,
            "restored_chunks": len(result['ids']),
            "document_id": filename,
            "collection": kb_name
        }

    def get_document_chunks(
        self,
        kb_name: str,
        filename: str,
        status: str = None
    ) -> List[Dict]:
        """
        获取文档的chunks列表

        Args:
            kb_name: 向量库名称
            filename: 文件名
            status: 状态过滤（active/deprecated/superseded）

        Returns:
            chunks列表
        """
        collection = self.get_collection(kb_name)
        if not collection:
            return []

        # 构建查询条件
        where_filter = {"source": filename}
        if status:
            where_filter["status"] = status

        result = collection.get(where=where_filter)

        return [
            {
                "id": id,
                "document": doc,
                "metadata": meta,
                "status": meta.get("status", "active"),
                "version": meta.get("version", "v1")
            }
            for id, doc, meta in zip(
                result['ids'],
                result['documents'],
                result['metadatas']
            )
        ]

    def get_document_info(self, kb_name: str, filename: str) -> Optional[Dict]:
        """
        获取文档基本信息

        Args:
            kb_name: 向量库名称
            filename: 文件名

        Returns:
            文档信息
        """
        collection = self.get_collection(kb_name)
        if not collection:
            return None

        result = collection.get(where={"source": filename})

        if not result['ids']:
            return None

        # 统计状态
        status_counts = {}
        for meta in result['metadatas']:
            status = meta.get("status", "active")
            status_counts[status] = status_counts.get(status, 0) + 1

        # 获取主要状态
        main_status = "active"
        if status_counts.get("deprecated", 0) > status_counts.get("active", 0):
            main_status = "deprecated"
        elif status_counts.get("superseded", 0) > 0:
            main_status = "superseded"

        # 获取第一个chunk的元数据作为文档元数据
        first_meta = result['metadatas'][0] if result['metadatas'] else {}

        return {
            "document_id": filename,
            "collection": kb_name,
            "total_chunks": len(result['ids']),
            "status": main_status,
            "status_counts": status_counts,
            "version": first_meta.get("version", "v1"),
            "effective_date": first_meta.get("effective_date"),
            "deprecated_date": first_meta.get("deprecated_date"),
            "deprecated_reason": first_meta.get("deprecated_reason"),
            "security_level": first_meta.get("security_level", "public")
        }

    def list_documents_by_status(
        self,
        kb_name: str,
        status: str = None
    ) -> List[Dict]:
        """
        按状态列出文档

        Args:
            kb_name: 向量库名称
            status: 状态过滤（active/deprecated/superseded）

        Returns:
            文档列表
        """
        collection = self.get_collection(kb_name)
        if not collection:
            return []

        result = collection.get()

        # 按文件名分组并统计状态
        doc_info = {}
        for meta in result.get('metadatas', []):
            source = meta.get('source', 'unknown')
            chunk_status = meta.get('status', 'active')

            if source not in doc_info:
                doc_info[source] = {
                    "source": source,
                    "chunks": 0,
                    "status_counts": {},
                    "collection": kb_name
                }

            doc_info[source]["chunks"] += 1
            doc_info[source]["status_counts"][chunk_status] = \
                doc_info[source]["status_counts"].get(chunk_status, 0) + 1

        # 计算主要状态
        result_list = []
        for doc in doc_info.values():
            counts = doc["status_counts"]
            if counts.get("deprecated", 0) > counts.get("active", 0):
                doc["status"] = "deprecated"
            elif counts.get("superseded", 0) > 0:
                doc["status"] = "superseded"
            else:
                doc["status"] = "active"

            # 状态过滤
            if status is None or doc["status"] == status:
                result_list.append(doc)

        return result_list

    def search_with_status_filter(
        self,
        kb_name: str,
        query_vector: List[float],
        top_k: int = 5,
        status_filter: str = "active"
    ) -> Optional[SearchResult]:
        """
        带状态过滤的检索

        Args:
            kb_name: 向量库名称
            query_vector: 查询向量
            top_k: 返回数量
            status_filter: 状态过滤（active/deprecated/all）

        Returns:
            检索结果
        """
        collection = self.get_collection(kb_name)
        if not collection or collection.count() == 0:
            return None

        # 构建查询条件
        where_filter = None
        if status_filter != "all":
            where_filter = {"status": status_filter}

        # 向量检索
        result = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where_filter
        )

        if not result['ids'] or not result['ids'][0]:
            return None

        return SearchResult(
            ids=result['ids'][0],
            documents=result['documents'][0],
            metadatas=result['metadatas'][0],
            distances=result['distances'][0],
            collection_name=kb_name
        )

    def find_deprecated_versions(
        self,
        kb_names: List[str],
        query_vector: List[float],
        top_k: int = 3
    ) -> List[Dict]:
        """
        查找与查询相关的已废止版本

        Args:
            kb_names: 向量库名称列表
            query_vector: 查询向量
            top_k: 每个库返回数量

        Returns:
            已废止版本的提示列表
        """
        hints = []

        for kb_name in kb_names:
            result = self.search_with_status_filter(
                kb_name,
                query_vector,
                top_k=top_k,
                status_filter="deprecated"
            )

            if result:
                for doc, meta, score in zip(
                    result.documents,
                    result.metadatas,
                    result.distances
                ):
                    # 相似度阈值
                    sim_score = 1 - score  # cosine距离转相似度
                    if sim_score >= 0.7:
                        hints.append({
                            "document": meta.get("source", ""),
                            "collection": kb_name,
                            "status": "deprecated",
                            "deprecated_date": meta.get("deprecated_date", ""),
                            "deprecated_reason": meta.get("deprecated_reason", ""),
                            "similarity": sim_score,
                            "snippet": doc[:100] + "..." if len(doc) > 100 else doc,
                            "message": self._build_deprecation_hint(meta)
                        })

        return hints

    def _build_deprecation_hint(self, metadata: Dict) -> str:
        """构建废止提示消息"""
        deprecated_date = metadata.get("deprecated_date", "")
        deprecated_reason = metadata.get("deprecated_reason", "")

        date_str = deprecated_date[:10] if deprecated_date else "未知日期"
        reason_str = f"，原因：{deprecated_reason}" if deprecated_reason else ""

        return f"⚠️ 该文档已于 {date_str} 废止{reason_str}，内容不再有效"


# ==================== 全局实例 ====================

_kb_manager: Optional[KnowledgeBaseManager] = None


def get_kb_manager() -> KnowledgeBaseManager:
    """获取全局知识库管理器实例"""
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager
