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
    from knowledge.manager import KnowledgeBaseManager

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
from pathlib import Path
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


# ==================== 辅助函数 ====================

def _get_doc_type(filename: str) -> str:
    """
    根据文件扩展名判断文档类型

    Args:
        filename: 文件名

    Returns:
        文档类型: pdf, word, excel, ppt, other
    """
    ext = Path(filename).suffix.lower()
    if ext == '.pdf':
        return 'pdf'
    elif ext in ('.docx', '.doc'):
        return 'word'
    elif ext in ('.xlsx', '.xls'):
        return 'excel'
    elif ext in ('.pptx', '.ppt'):
        return 'ppt'
    return 'other'


def _extract_figure_number(caption: str, section: str = '') -> str:
    """
    从 caption 或 section 中提取图号（增强版）

    支持格式：
    - 图2.4, 图2-4
    - Fig.2.4, Fig 2.4, Figure 2.4
    - （图2）

    Args:
        caption: 图片标题/说明
        section: 章节信息

    Returns:
        图号字符串，如 "2.4"；未找到返回空字符串
    """
    import re

    text = f"{caption} {section}"

    patterns = [
        r'图\s*(\d+[\.\-]\d+)',      # 图2.4, 图2-4
        r'Fig\.?\s*(\d+[\.\-]\d+)',  # Fig.2.4, Fig 2.4
        r'Figure\s*(\d+[\.\-]\d+)',  # Figure 2.4
        r'[（(]\s*图\s*(\d+)\s*[)）]',  # （图2）
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # 统一格式：2.4
            return match.group(1).replace('-', '.')

    return ""


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

# 部门名称映射：中文名 -> 英文标识（用于向量库命名）
# 向量库名称必须符合 ChromaDB 规范：只能包含 [a-zA-Z0-9._-]
DEPARTMENT_NAME_MAP = {
    # 中文名 -> 英文标识
    "财务部": "finance",
    "财务": "finance",
    "人事部": "hr",
    "人事": "hr",
    "人力资源部": "hr",
    "人力资源": "hr",
    "技术部": "tech",
    "技术": "tech",
    "研发部": "tech",
    "研发": "tech",
    "运营部": "operation",
    "运营": "operation",
    "市场部": "marketing",
    "市场": "marketing",
    "法务部": "legal",
    "法务": "legal",
    "行政部": "admin",
    "行政": "admin",
    # 英文标识 -> 英文标识（保持不变）
    "finance": "finance",
    "hr": "hr",
    "tech": "tech",
    "operation": "operation",
    "marketing": "marketing",
    "legal": "legal",
    "admin": "admin",
}


def normalize_department_name(department: str) -> str:
    """
    将部门名称标准化为英文标识

    Args:
        department: 原始部门名称（可能是中文或英文）

    Returns:
        标准化的英文标识（用于向量库命名）
    """
    if not department:
        return ""

    # 优先查找映射表
    if department in DEPARTMENT_NAME_MAP:
        return DEPARTMENT_NAME_MAP[department]

    # 如果不在映射表中，尝试转换为拼音或返回空
    # 这里简单处理：如果是纯英文则直接返回，否则返回空
    if department.replace("_", "").replace("-", "").isalnum() and department.isascii():
        return department.lower()

    # 无法识别的中文部门名，记录警告
    logger.warning(f"无法识别的部门名称: {department}，请添加到 DEPARTMENT_NAME_MAP")
    return ""


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


# ==================== 语义增强辅助函数 ====================

def _extract_section(section_path: str, max_levels: int = 3) -> str:
    """
    动态截断章节路径

    保留核心 + 末尾，最多 max_levels 级

    Args:
        section_path: 完整章节路径
        max_levels: 最多保留级数（默认3级）

    Returns:
        截断后的章节路径
    """
    parts = [p.strip() for p in section_path.split('>') if p.strip()]

    if len(parts) <= max_levels:
        return ' > '.join(parts)

    # 保留"核心 + 末尾"：倒数第 max_levels 级到最后
    return ' > '.join(parts[-max_levels:])


def _build_semantic_content_for_text(chunk, page_info: dict, doc_type: str) -> str:
    """
    构建语义增强内容（文本类型）

    PDF 和 Word 差异化处理：
    - PDF: 有 text_level、bbox，标题识别准确
    - Word: 无 text_level、bbox，依赖启发式识别

    Args:
        chunk: MinerUChunk 对象
        page_info: 页面信息字典
        doc_type: 文档类型 ('pdf', 'word', 'excel', 'ppt')

    Returns:
        语义增强后的内容字符串
    """
    parts = []

    # 1. 标题：不加标签，权重更高
    title = getattr(chunk, 'title', '') or ''
    # title 可能是列表，需要转换为字符串
    if isinstance(title, list):
        title = ' '.join(str(t) for t in title if t) or ''
    text_level = getattr(chunk, 'text_level', 0)

    if title and title.strip() and text_level > 0:
        # 直接放标题，不加【标题】标签，让 embedding 更聚焦
        parts.append(title.strip())

    # 2. 章节：动态截断（最多3级，避免噪声）
    section = page_info.get('section_path', '') or page_info.get('section', '')
    # section 可能是列表，需要转换为字符串
    if isinstance(section, list):
        section = ' > '.join(str(s) for s in section if s) or ''
    if section and section.strip():
        section = _extract_section(section, max_levels=3)
        parts.append(f"主题：{section}")

    # 3. 内容：核心信息
    content = chunk.content if hasattr(chunk, 'content') else page_info.get('text', '')
    if isinstance(content, list):
        content = '\n'.join(str(item) for item in content)
    parts.append(content)

    return "\n".join(parts)


def _build_semantic_content_for_table(table_md: str, page_info: dict, chunk, doc_type: str) -> str:
    """
    构建语义增强内容（表格类型）

    PDF 和 Word 差异化处理：
    - PDF: 有 table_caption，直接使用
    - Word: 无 table_caption，从表格内容推断

    Args:
        table_md: 表格 Markdown 内容
        page_info: 页面信息字典
        chunk: MinerUChunk 对象
        doc_type: 文档类型

    Returns:
        语义增强后的内容字符串
    """
    parts = []

    # 1. 章节（动态截断，最多3级）
    section = page_info.get('section_path', '') or page_info.get('section', '')
    # section 可能是列表，需要转换为字符串
    if isinstance(section, list):
        section = ' > '.join(str(s) for s in section if s) or ''
    if section and section.strip():
        section = _extract_section(section, max_levels=3)
        parts.append(f"主题：{section}")

    # 2. 表格标题
    caption = getattr(chunk, 'title', '') or ''
    # caption 可能是列表，需要转换为字符串
    if isinstance(caption, list):
        caption = ' '.join(str(c) for c in caption if c) or ''
    if caption and caption.strip() and caption != "表格":
        parts.append(f"表格：{caption.strip()}")

    # 3. 表头（关键语义）
    lines = table_md.split('\n')
    headers = []
    for line in lines:
        if line.startswith('|') and '---' not in line:
            headers = [h.strip() for h in line.split('|') if h.strip()]
            if headers and len(headers) > 1:
                parts.append(f"字段：{', '.join(headers)}")
            break

    # 4. 表格描述（语义摘要，不截断数据）
    row_count = len([l for l in lines if l.startswith('|') and '---' not in l])
    if headers:
        parts.append(f"描述：该表包含{row_count}行数据，记录各{', '.join(headers[:3])}信息")
    else:
        parts.append(f"描述：该表包含{row_count}行数据")

    # 5. 示例数据（仅展示一行，不截断表格）
    for line in lines:
        if line.startswith('|') and '---' not in line and headers:
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells and cells != headers:
                example_parts = []
                for i, h in enumerate(headers[:2]):
                    if i < len(cells):
                        example_parts.append(f"{h}={cells[i]}")
                if example_parts:
                    parts.append(f"示例：{', '.join(example_parts)}")
                break

    return "\n".join(parts)


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
            # 检查向量库是否实际存在
            existing = self.get_collection(kb_name)
            if existing and existing.count() > 0:
                return False, f"向量库 '{kb_name}' 已存在"
            # 元数据存在但向量库不存在，清理元数据继续创建
            del self._metadata["collections"][kb_name]

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

        会检测 ChromaDB 中实际存在的向量库，并自动补充缺失的元数据。

        Returns:
            向量库信息列表
        """
        result = []

        # 获取 ChromaDB 中实际存在的向量库
        try:
            # 使用 public_kb 的 client 获取所有集合（它们共享同一个 client）
            client = self._get_client("public_kb")
            actual_collections = [c.name for c in client.list_collections()]
        except Exception as e:
            logger.warning(f"获取 ChromaDB 集合列表失败: {e}")
            actual_collections = list(self._metadata.get("collections", {}).keys())

        # 确保 ChromaDB 中的每个集合都有元数据记录
        for name in actual_collections:
            if name not in self._metadata.get("collections", {}):
                # 自动补充缺失的元数据
                if "collections" not in self._metadata:
                    self._metadata["collections"] = {}
                from datetime import datetime
                self._metadata["collections"][name] = {
                    "display_name": name,
                    "department": "",
                    "description": "",
                    "created_at": datetime.now().isoformat()
                }
                logger.info(f"自动补充向量库元数据: {name}")

        # 保存更新后的元数据
        self._save_metadata()

        # 从元数据构建返回结果
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

    def update_image_descriptions(self, kb_name: str) -> dict:
        """
        更新图片切片的轻量级描述（提取图号/表号）

        用于已入库的文档，重新生成图片描述以包含图号信息

        Args:
            kb_name: 向量库名称

        Returns:
            更新统计信息
        """
        try:
            collection = self.get_collection(kb_name)
            if not collection:
                return {"success": False, "error": "向量库不存在"}

            # 获取所有图片/图表切片
            result = collection.get(include=['documents', 'metadatas'])

            image_count = 0
            updated_count = 0
            updated_ids = []
            updated_docs = []
            updated_metas = []

            for i, (id_, doc, meta) in enumerate(zip(result['ids'], result['documents'], result['metadatas'])):
                chunk_type = meta.get('chunk_type', '')
                if chunk_type not in ('image', 'chart'):
                    continue

                image_count += 1

                # 提取图号（从多个来源）
                import re
                figure_number = ""
                table_number = ""

                # 来源列表
                sources = [
                    doc,  # 完整文档
                    meta.get('section', ''),
                    meta.get('section_path', ''),
                    meta.get('caption', '')
                ]

                for source_text in sources:
                    if not source_text:
                        continue

                    # 提取图号
                    if not figure_number:
                        fig_match = re.search(r'(?:[见如及和与])?图\s*(\d+\.?\d*)', source_text)
                        if fig_match:
                            figure_number = fig_match.group(1)

                    # 提取表号
                    if not table_number:
                        table_match = re.search(r'(?:[见如及和与])?表\s*(\d+\.?\d*)', source_text)
                        if table_match:
                            table_number = table_match.group(1)

                # 如果找到图号，更新描述
                if figure_number or table_number:
                    # 构建新描述（在开头添加图号/表号）
                    prefix_parts = []
                    if figure_number:
                        prefix_parts.append(f"图{figure_number}")
                    if table_number:
                        prefix_parts.append(f"表{table_number}")

                    prefix = " ".join(prefix_parts)

                    # 检查当前描述是否已包含图号
                    has_figure_in_start = False
                    first_line = doc.split('\n')[0] if doc else ""
                    for pn in prefix_parts:
                        if pn in first_line:
                            has_figure_in_start = True
                            break

                    if not has_figure_in_start:
                        # 在描述开头添加图号
                        new_doc = f"{prefix} {doc}"
                        updated_ids.append(id_)
                        updated_docs.append(new_doc)
                        updated_metas.append(meta)
                        updated_count += 1

            # 批量更新
            if updated_ids:
                # 需要重新生成向量
                from sentence_transformers import SentenceTransformer
                embedding_model = SentenceTransformer('models/bge-base-zh-v1.5')

                for id_, doc, meta in zip(updated_ids, updated_docs, updated_metas):
                    vector = embedding_model.encode(doc).tolist()
                    if isinstance(vector[0], list):
                        vector = vector[0]

                    collection.update(
                        ids=[id_],
                        embeddings=[vector],
                        documents=[doc],
                        metadatas=[meta]
                    )

                # 重建 BM25 索引
                self.rebuild_bm25_index(kb_name)

            logger.info(f"更新图片描述: {kb_name}, 图片数: {image_count}, 更新数: {updated_count}")
            return {
                "success": True,
                "image_count": image_count,
                "updated_count": updated_count
            }

        except Exception as e:
            logger.error(f"更新图片描述失败: {e}")
            return {"success": False, "error": str(e)}

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
            department: 用户部门（支持中文名或英文标识）
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

        # 本部门向量库 - 使用标准化部门名称
        if department:
            # 将部门名称标准化为英文标识
            normalized_dept = normalize_department_name(department)
            if normalized_dept:
                dept_kb = f"dept_{normalized_dept}"
                if dept_kb in self._metadata.get("collections", {}):
                    # 检查操作权限
                    if operation == "read":
                        result.append(dept_kb)
                    elif operation in ("write", "delete", "sync"):
                        # 只有 manager 可以对本部门进行写操作
                        if role == "manager":
                            result.append(dept_kb)
            else:
                logger.warning(f"部门名称无法标准化: {department}")

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
        extra_metadata: dict = None,
        enable_table_summary: bool = True,
        enable_image_description: bool = False,
        file_content: bytes = None  # 新增：支持直接传入文件内容
    ) -> int:
        """
        添加文件到指定向量库（v6 支持企业文件系统）

        使用统一的 parse_document() 入口，支持：
        - PDF/DOCX/PPTX/图片 → MinerU 解析
        - XLSX/XLS → Pandas 解析
        - TXT → 文本解析

        Args:
            kb_name: 向量库名称
            filepath: 文件路径（相对路径或绝对路径）
            embedding_model: 向量模型（可选，默认使用 engine 的）
            extra_metadata: 额外的元数据（如 status, version 等）
            enable_table_summary: 是否启用表格摘要管道（LLM 生成摘要）
            enable_image_description: 是否启用图片描述管道（VLM 生成描述）
            file_content: 文件二进制内容（可选，用于企业文件系统集成）

        Returns:
            添加的片段数量
        """
        collection = self.get_collection(kb_name)
        if not collection:
            logger.error(f"获取向量库失败: {kb_name}")
            return 0

        # 确保元数据中有该向量库记录（get_or_create_collection 可能创建了集合但没更新元数据）
        if kb_name not in self._metadata.get("collections", {}):
            if "collections" not in self._metadata:
                self._metadata["collections"] = {}
            from datetime import datetime
            self._metadata["collections"][kb_name] = {
                "display_name": kb_name,
                "department": "",
                "description": "",
                "created_at": datetime.now().isoformat()
            }
            self._save_metadata()
            logger.info(f"更新向量库元数据: {kb_name}")

        # 获取向量模型
        if embedding_model is None:
            try:
                from core.engine import get_engine
                engine = get_engine()
                if not engine._initialized:
                    engine.initialize()
                embedding_model = engine.embedding_model
            except Exception as e:
                logger.error(f"无法加载向量模型: {e}")
                return 0

        filename = os.path.basename(filepath)
        extra_metadata = extra_metadata or {}
        total_chunks = 0  # 在 try 块外初始化，确保异常时也可访问

        try:
            # 使用统一解析入口
            from parsers import parse_document, convert_to_rag_format, SUPPORTED_FORMATS

            ext = os.path.splitext(filepath)[1].lower()
            if ext not in SUPPORTED_FORMATS:
                logger.warning(f"不支持的文件格式: {ext}")
                return 0

            # 解析文档
            logger.info(f"解析文档: {filename}")
            parse_result = parse_document(
                filepath,
                output_base=".data/mineru_temp",
                images_output=".data/images",
                cleanup_after_image_move=True  # 解析后自动清理临时输出
            )

            # 转换为 RAG 格式
            pages_content = convert_to_rag_format(parse_result)
            chunks = parse_result.get('chunks', [])

            if not pages_content:
                logger.warning(f"文档解析结果为空: {filename}")
                return 0

            # 按 chunk_type 分类处理
            text_chunks = []
            table_chunks = []
            image_chunks = []

            for i, (page_info, chunk) in enumerate(zip(pages_content, chunks)):
                chunk_type = page_info.get('chunk_type', 'text')
                if chunk_type == 'table':
                    table_chunks.append((i, page_info, chunk))
                elif chunk_type in ('image', 'chart'):
                    # 图片和图表统一处理
                    image_chunks.append((i, page_info, chunk))
                else:
                    text_chunks.append((i, page_info, chunk))

            # 章节内序号计数器（用于 Word 文档语义定位）
            section_counters = {}  # section_path -> 当前序号

            # 1. 处理文本块 - 直接向量化入库
            for idx, page_info, chunk in text_chunks:
                text = page_info.get('text', '')
                if not text.strip():
                    continue

                # 使用 chunk.content（已包含 Markdown 格式）
                content = chunk.content if hasattr(chunk, 'content') else text

                # 确保 content 是字符串类型，防止解析器产出 list 导致 Chroma 报错
                if isinstance(content, list):
                    content = '\n'.join(str(item) for item in content)
                elif not isinstance(content, str):
                    content = str(content)

                # 构建语义增强内容用于 embedding
                doc_type = _get_doc_type(filename)
                semantic_content = _build_semantic_content_for_text(chunk, page_info, doc_type)
                vector = embedding_model.encode(semantic_content).tolist()
                # 确保是 1D 列表（单个文档的向量）
                if isinstance(vector[0], list):
                    vector = vector[0]
                chunk_id = f"{filename}_text_{idx}"

                # 计算章节内序号（用于 Word 文档语义定位）
                section = page_info.get('section_path', '') or page_info.get('section', '')
                # section 可能是列表，需要转换为字符串
                if isinstance(section, list):
                    section = ' > '.join(str(s) for s in section if s) or ''
                if section not in section_counters:
                    section_counters[section] = 0
                section_counters[section] += 1
                section_chunk_id = section_counters[section]

                metadata = {
                    'source': filename,
                    'page': page_info.get('page', 0),
                    'page_end': page_info.get('page_end', page_info.get('page', 0)),  # 结束页码
                    'chunk_index': idx,
                    'chunk_id': chunk_id,  # 切片唯一标识
                    'chunk_type': 'text',
                    'section': section,
                    'section_chunk_id': section_chunk_id,  # 章节内序号（用于语义定位）
                    'doc_type': _get_doc_type(filename),  # 文档类型: pdf/word/excel/ppt
                    'preview': content[:50] if len(content) > 50 else content,  # 可搜索片段
                    'has_table': False,
                    'collection': collection.name,
                    **extra_metadata
                }

                # ========== P2：图文关联索引 ==========
                # 提取文本中的图表引用
                referenced_images = self._extract_figure_references(content)
                if referenced_images:
                    metadata['referenced_images'] = referenced_images

                # 添加 bbox（仅当存在时）
                bbox = page_info.get('bbox')
                if bbox:
                    metadata['bbox'] = json.dumps(bbox)
                    metadata['bbox_mode'] = 'normalized'

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[content],
                    metadatas=[metadata]
                )
                total_chunks += 1

            # 2. 处理表格块 - 原始 Markdown 入库（Phase 3：不用 LLM）
            for idx, page_info, chunk in table_chunks:
                # 优先使用 page_info['text']（包含转换后的表格 Markdown），
                # 而非 chunk.content（可能仅是 caption 如 "表格"）
                table_md = page_info.get('text', '') or (chunk.content if hasattr(chunk, 'content') else '')

                # 确保 table_md 是字符串类型
                if isinstance(table_md, list):
                    table_md = '\n'.join(str(item) for item in table_md)
                elif not isinstance(table_md, str):
                    table_md = str(table_md)

                if not table_md.strip():
                    continue

                chunk_id = f"{filename}_table_{idx}"

                # 计算章节内序号
                section = page_info.get('section_path', '') or page_info.get('section', '')
                # section 可能是列表，需要转换为字符串
                if isinstance(section, list):
                    section = ' > '.join(str(s) for s in section if s) or ''
                if section not in section_counters:
                    section_counters[section] = 0
                section_counters[section] += 1
                section_chunk_id = section_counters[section]

                # 表格元数据
                table_meta = {
                    'source': filename,
                    'page': page_info.get('page', 0),
                    'page_end': page_info.get('page_end', page_info.get('page', 0)),  # 结束页码
                    'chunk_index': idx,
                    'chunk_id': chunk_id,  # 切片唯一标识
                    'chunk_type': 'table',
                    'section': section,
                    'section_chunk_id': section_chunk_id,  # 章节内序号
                    'doc_type': _get_doc_type(filename),  # 文档类型: pdf/word/excel/ppt
                    'preview': table_md[:50] if len(table_md) > 50 else table_md,  # 可搜索片段
                    'has_table': True,
                    'collection': collection.name,
                    'has_summary': False,  # 标记：未调用 LLM
                    **extra_metadata
                }

                # 添加 bbox（仅当存在时）
                bbox = page_info.get('bbox')
                if bbox:
                    table_meta['bbox'] = json.dumps(bbox)
                    table_meta['bbox_mode'] = 'normalized'

                # 如果表格有图片，添加 image_path
                table_image_path = chunk.image_path if hasattr(chunk, 'image_path') and chunk.image_path else None
                if table_image_path:
                    table_meta['image_path'] = table_image_path

                # 如果表格有关联图片列表（嵌入表格的图片），添加 images 字段（JSON 字符串）
                if hasattr(chunk, 'images') and chunk.images:
                    table_meta['images'] = json.dumps(chunk.images) if isinstance(chunk.images, list) else chunk.images

                # 构建语义增强内容用于 embedding
                doc_type = table_meta.get('doc_type', 'other')
                semantic_content = _build_semantic_content_for_table(table_md, page_info, chunk, doc_type)
                vector = embedding_model.encode(semantic_content).tolist()
                if isinstance(vector[0], list):
                    vector = vector[0]

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[table_md],
                    metadatas=[table_meta]
                )

                # 存储原始表格到 DocStore（用于后续展示）
                self._store_original_table(chunk_id, table_md, table_meta)

                total_chunks += 1

            # 3. 处理图片块 - 轻量描述管道（Phase 2：不用 VLM）
            for idx, page_info, chunk in image_chunks:
                image_path = chunk.image_path if hasattr(chunk, 'image_path') else page_info.get('image_path')
                if not image_path:
                    continue

                # 构建完整图片路径（图片已移动到 .data/images）
                if not os.path.isabs(image_path):
                    full_image_path = os.path.join('.data/images', image_path)
                else:
                    full_image_path = image_path

                # 图片过滤（Phase 1）
                context_text = chunk.content if hasattr(chunk, 'content') else ""
                caption = page_info.get('caption', '')
                if not self.should_process_image(full_image_path, context_text, caption):
                    continue

                chunk_id = f"{filename}_image_{idx}"

                # 保留原始 chunk_type（image 或 chart）
                original_chunk_type = page_info.get('chunk_type', 'image')

                # 获取 caption（用于图片检索）
                caption = page_info.get('caption', '') or (chunk.title if hasattr(chunk, 'title') else '')

                # 计算章节内序号
                section = page_info.get('section_path', '') or page_info.get('section', '')
                # section 可能是列表，需要转换为字符串
                if isinstance(section, list):
                    section = ' > '.join(str(s) for s in section if s) or ''
                if section not in section_counters:
                    section_counters[section] = 0
                section_counters[section] += 1
                section_chunk_id = section_counters[section]

                image_meta = {
                    'source': filename,
                    'page': page_info.get('page', 0),
                    'page_end': page_info.get('page_end', page_info.get('page', 0)),  # 结束页码
                    'chunk_index': idx,
                    'chunk_id': chunk_id,  # 切片唯一标识
                    'chunk_type': original_chunk_type,
                    'section': section,
                    'section_chunk_id': section_chunk_id,  # 章节内序号
                    'doc_type': _get_doc_type(filename),  # 文档类型: pdf/word/excel/ppt
                    'caption': caption,  # 图片标题/说明
                    'figure_number': _extract_figure_number(caption, page_info.get('section', '')),  # 图号
                    'has_table': False,
                    'collection': collection.name,
                    'image_path': image_path,  # 存储相对路径（文件名）
                    'has_vlm_desc': False,  # 标记：未调用 VLM
                    **extra_metadata
                }

                # 添加 bbox（仅当存在时）
                bbox = page_info.get('bbox')
                if bbox:
                    image_meta['bbox'] = json.dumps(bbox)
                    image_meta['bbox_mode'] = 'normalized'

                # 优先使用 VLM 缓存（如果存在）
                vlm_desc = self._get_vlm_cache(full_image_path)

                if vlm_desc:
                    # 使用 VLM 描述
                    full_description = vlm_desc
                    image_meta['has_vlm_desc'] = True
                    image_meta['preview'] = vlm_desc[:50] if len(vlm_desc) > 50 else vlm_desc
                    logger.info(f"使用 VLM 缓存: {image_path}")
                else:
                    # 生成轻量描述（包含上下文）
                    full_description = self.generate_lightweight_image_description(full_image_path, chunk, page_info)
                    image_meta['preview'] = full_description[:50] if len(full_description) > 50 else full_description

                # ========== P1：双字段存储 ==========
                # 生成短摘要（用于检索匹配）
                short_summary = self.generate_image_short_summary(chunk, page_info, full_description)

                # 完整描述存到 metadata（用于 LLM 上下文）
                image_meta['full_description'] = full_description

                # 向量化入库（使用短摘要）
                vector = embedding_model.encode(short_summary).tolist()
                if isinstance(vector[0], list):
                    vector = vector[0]

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[short_summary],  # 短摘要用于检索
                    metadatas=[image_meta]
                )

                # 图片路径存入 DocStore
                self._store_image_reference(chunk_id, image_path, image_meta)

                total_chunks += 1

            # 重建 BM25 索引
            if total_chunks > 0:
                self._rebuild_bm25_index(kb_name)

            logger.info(f"添加文件到 {kb_name}: {filename}, 片段数: {total_chunks} "
                       f"(文本:{len(text_chunks)}, 表格:{len(table_chunks)}, 图片:{len(image_chunks)})")

        except Exception as e:
            import traceback
            logger.error(f"添加文件失败: {filepath}, 错误: {e}\n{traceback.format_exc()}")

        return total_chunks

    def _generate_table_summary(self, table_md: str, chunk) -> str:
        """
        生成表格摘要（带容错）

        Args:
            table_md: 表格 Markdown 内容（应包含实际表格数据）
            chunk: 原始 chunk 对象（用于提取元数据）

        Returns:
            表格摘要文本
        """
        import re

        # 从 Markdown 内容计算实际行数（匹配 | 开头的行，排除分隔行）
        md_lines = [line for line in table_md.split('\n') if line.strip().startswith('|')]
        separator_lines = [line for line in md_lines if re.match(r'^[\|\s\-:]+$', line.strip())]
        row_count = len(md_lines) - len(separator_lines)

        # 智能提取标题：chunk.title → 表格首行列名 → 降级
        title = getattr(chunk, 'title', '') if hasattr(chunk, 'title') else ''
        # title 可能是列表，需要转换为字符串
        if isinstance(title, list):
            title = ' '.join(str(t) for t in title if t) or ''
        if not title or title == '表格':
            title = self._extract_table_title(table_md)

        # 小表格跳过 LLM（仅限 < 3 数据行且 < 200 字符的微型表格）
        if row_count < 3 and len(table_md) < 200:
            return f"小型表格（{row_count}行）：{title}"

        try:
            from config import get_llm_client, DASHSCOPE_MODEL
            client = get_llm_client()

            prompt = f"""请用简洁的语言总结以下表格的内容，包括：
1. 表格主题
2. 主要列名
3. 关键数据趋势或结论

表格内容：
{table_md[:2000]}

请直接输出摘要（不超过100字）："""

            response = client.chat.completions.create(
                model=DASHSCOPE_MODEL,  # 使用配置文件中的模型
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(f"表格摘要生成失败: {e}，使用降级摘要")
            return f"表格（{row_count}行）：{title}"

    @staticmethod
    def _extract_table_title(table_md: str) -> str:
        """
        从表格 Markdown 内容提取标题（列名摘要）

        优先从 Markdown 表格首行提取列名，
        如无法提取，使用【表格】前缀后的文本。

        Args:
            table_md: 表格 Markdown 内容

        Returns:
            提取的标题字符串
        """
        import re

        # 尝试从【表格】标记后提取标题
        title_match = re.search(r'【表格】(.+?)\n', table_md)
        if title_match:
            extracted = title_match.group(1).strip()
            if extracted and extracted != '表格':
                return extracted

        # 尝试从 Markdown 表头行提取列名
        for line in table_md.split('\n'):
            line = line.strip()
            if line.startswith('|') and not re.match(r'^[\|\s\-:]+$', line):
                cols = [c.strip() for c in line.split('|') if c.strip()]
                if cols:
                    display = '、'.join(cols[:4])
                    if len(cols) > 4:
                        display += '等'
                    return display

        # 尝试从 HTML 标签提取（如 <strong>xxx</strong>）
        strong_match = re.findall(r'<strong>(.*?)</strong>', table_md[:300])
        if strong_match:
            cols = [s.strip() for s in strong_match if s.strip() and s.strip() not in ('', ':', '：')]
            if cols:
                display = '、'.join(cols[:4])
                if len(cols) > 4:
                    display += '等'
                return display

        return "数据表格"

    def should_process_image(self, image_path: str, context_text: str, caption: str = "") -> bool:
        """
        判断图片是否值得处理（Phase 1：图片过滤）

        Args:
            image_path: 图片路径
            context_text: 上下文文本
            caption: 图片标题

        Returns:
            是否处理该图片
        """
        filename = os.path.basename(image_path).lower()

        # 规则 1：文件名过滤
        junk_keywords = ["logo", "icon", "qr", "watermark", "banner", "button", "avatar"]
        if any(kw in filename for kw in junk_keywords):
            logger.debug(f"图片过滤：文件名包含垃圾关键词 - {filename}")
            return False

        # 规则 2：尺寸过滤
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                width, height = img.size
                if width < 100 or height < 100:
                    logger.debug(f"图片过滤：尺寸过小 ({width}x{height}) - {filename}")
                    return False
        except Exception as e:
            logger.warning(f"图片尺寸检查失败: {e}")
            # 尺寸检查失败不影响处理
            pass

        # 规则 3：上下文相关性（放宽要求）
        # 只要有 caption 或者有一定上下文就保留
        if len(caption) >= 3:
            return True
        if len(context_text) >= 10:
            return True

        # 如果完全没有上下文信息，也保留（可能是独立图片）
        logger.debug(f"图片保留：{filename}")
        return True

    def _get_vlm_cache(self, image_path: str) -> str | None:
        """
        检查是否有 VLM 缓存描述

        Args:
            image_path: 图片完整路径

        Returns:
            VLM 描述文本，如果不存在则返回 None
        """
        import hashlib
        from pathlib import Path

        try:
            if not os.path.exists(image_path):
                return None

            # 计算图片哈希
            img_hash = hashlib.md5(open(image_path, 'rb').read()).hexdigest()

            # 检查缓存文件
            cache_file = Path(f'.data/cache/vlm/{img_hash}.txt')
            if cache_file.exists():
                return cache_file.read_text(encoding='utf-8')
        except Exception as e:
            logger.debug(f"检查 VLM 缓存失败: {e}")

        return None

    def generate_image_short_summary(self, chunk, page_info: dict, full_description: str = "") -> str:
        """
        生成图片短摘要（用于向量检索匹配）

        短摘要格式：图2.3：2003-2022年三峡电站逐年发电量柱状图，峰值1118亿千瓦时
        特点：20-40字，关键词密集，便于检索匹配

        Args:
            chunk: 原始 chunk 对象
            page_info: 页面信息字典
            full_description: 完整描述（VLM 或轻量描述）

        Returns:
            短摘要文本
        """
        import re

        # 1. 提取图号/表号
        figure_number = ""
        table_number = ""

        # 从多个来源提取
        section = page_info.get('section_path', '') or page_info.get('section', '')
        title = chunk.title if hasattr(chunk, 'title') and chunk.title else ""
        caption = page_info.get('caption', '')

        for source in [section, title, caption, full_description]:
            if not source:
                continue
            # 提取图号
            fig_match = re.search(r'图\s*(\d+\.?\d*)', str(source))
            if fig_match and not figure_number:
                figure_number = fig_match.group(1)
            # 提取表号
            table_match = re.search(r'表\s*(\d+\.?\d*)', str(source))
            if table_match and not table_number:
                table_number = table_match.group(1)

        # 2. 提取核心主题（从完整描述或上下文）
        chunk_type = page_info.get('chunk_type', 'image')

        # 从完整描述中提取关键信息
        keywords = []

        # 提取年份范围
        year_match = re.search(r'(\d{4})\s*[-至到]\s*(\d{4})', full_description)
        if year_match:
            keywords.append(f"{year_match.group(1)}-{year_match.group(2)}年")

        # 提取关键数值
        num_match = re.search(r'(\d+\.?\d*)\s*(亿|万|千瓦时|吨|米)', full_description)
        if num_match:
            keywords.append(f"{num_match.group(1)}{num_match.group(2)}")

        # 从 section 中提取主题
        if section:
            # 提取章节主题（如"发电"、"航运"）
            section_parts = section.split('>')
            if section_parts:
                last_part = section_parts[-1].strip()
                # 提取主题词
                theme_match = re.search(r'(\d+\.?\d*)\s*(.+)', last_part)
                if theme_match:
                    keywords.append(theme_match.group(2).strip()[:10])

        # 3. 构建短摘要
        if chunk_type == 'chart':
            type_label = "图表"
            # 尝试从描述中提取图表类型
            if '柱状图' in full_description:
                type_label = "柱状图"
            elif '折线图' in full_description or '曲线图' in full_description:
                type_label = "折线图"
            elif '饼图' in full_description:
                type_label = "饼图"
        elif chunk_type == 'table':
            type_label = "表格"
        else:
            type_label = "图片"

        # 构建短摘要
        if figure_number:
            summary = f"图{figure_number}："
        elif table_number:
            summary = f"表{table_number}："
        else:
            summary = f"{type_label}："

        # 添加关键词
        if keywords:
            summary += "，".join(keywords[:3])

        # 从完整描述中提取主题句（前 30 字）
        if full_description and len(keywords) < 2:
            # 提取描述的第一句作为主题
            first_sentence = full_description.split('。')[0][:30]
            if first_sentence:
                summary += first_sentence

        # 限制长度（20-40 字）
        if len(summary) > 45:
            summary = summary[:42] + "..."

        return summary

    def _extract_figure_references(self, text: str) -> list:
        """
        提取文本中的图表引用（P2：图文关联索引）

        Args:
            text: 文本内容

        Returns:
            引用的图号/表号列表，如 ['2.3', '2.2']
        """
        import re

        references = []

        # 提取图号引用：见图2.3、如图2.3、图2.3、图 2.3 等
        fig_matches = re.findall(r'(?:[见如及和与])?图\s*(\d+\.?\d*)', text)
        references.extend(fig_matches)

        # 提取表号引用：见表2.2、如表2.2、表2.2、表 2.2 等
        table_matches = re.findall(r'(?:[见如及和与])?表\s*(\d+\.?\d*)', text)
        references.extend(table_matches)

        # 去重
        return list(set(references))

    def generate_lightweight_image_description(self, image_path: str, chunk, page_info: dict) -> str:
        """
        生成轻量级图片描述（包含上下文，用于语义检索）

        信息来源：图号/表号 + 标题/caption + 章节路径 + 页码 + 前后文本上下文

        Args:
            image_path: 图片路径
            chunk: 原始 chunk 对象
            page_info: 页面信息字典

        Returns:
            轻量级描述文本（包含上下文，便于语义检索命中）
        """
        import re
        parts = []

        # 1. 图片类型
        chunk_type = page_info.get('chunk_type', 'image')
        is_chart = chunk_type == 'chart'
        type_label = "图表" if is_chart else "图片"

        # 2. 提取图号/表号（关键！用于精确匹配）
        figure_number = ""
        table_number = ""

        # 从多个来源提取图号
        sources_to_check = []

        # 章节路径
        section = page_info.get('section_path', '') or page_info.get('section', '')
        if section:
            sources_to_check.append(section)

        # 标题
        title = chunk.title if hasattr(chunk, 'title') and chunk.title else ""
        if title:
            sources_to_check.append(title)

        # caption
        caption = page_info.get('caption', '')
        if caption:
            sources_to_check.append(caption)

        # 上下文
        context_before = ""
        context_after = ""
        if hasattr(chunk, 'context_before') and chunk.context_before:
            context_before = chunk.context_before[:500]
            sources_to_check.append(context_before)
        if hasattr(chunk, 'context_after') and chunk.context_after:
            context_after = chunk.context_after[:500]
            sources_to_check.append(context_after)

        # 从所有来源提取图号
        for source_text in sources_to_check:
            if not figure_number:
                fig_match = re.search(r'(?:[见如及和与])?图\s*(\d+\.?\d*)', source_text)
                if fig_match:
                    figure_number = fig_match.group(1)
            if not table_number:
                table_match = re.search(r'(?:[见如及和与])?表\s*(\d+\.?\d*)', source_text)
                if table_match:
                    table_number = table_match.group(1)

        # 3. 页码
        page = page_info.get('page', 0)

        # 4. 组装描述（图号/表号放在最前面）
        if figure_number:
            parts.append(f"图{figure_number}")
        if table_number:
            parts.append(f"表{table_number}")

        # 标题或 caption
        if caption and caption not in ("图片", "图表"):
            parts.append(caption)
        elif title and title not in ("图片", "图表"):
            parts.append(title)

        if section:
            parts.append(f"位于「{section}」")

        parts.append(f"第{page}页")

        # 组装完整描述
        description_parts = [f"{type_label}：{'，'.join(parts)}"]

        # 添加上下文（用于语义检索）
        if context_before:
            description_parts.append(f"前文：{context_before}")
        if context_after:
            description_parts.append(f"后文：{context_after}")

        return "\n".join(description_parts)

    def _generate_image_description(self, image_path: str, metadata: dict = None) -> str:
        """
        生成图片描述（VLM），结合元数据增强描述质量

        Args:
            image_path: 图片路径
            metadata: 图片元数据（包含 section、page、caption、上下文等）

        Returns:
            图片描述文本
        """
        try:
            import base64
            from config import get_llm_client, DASHSCOPE_BASE_URL, DASHSCOPE_API_KEY, DASHSCOPE_VL_MODEL

            # 读取图片并编码
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # 获取图片格式
            ext = os.path.splitext(image_path)[1].lower()
            image_format = 'png' if ext in ['.png', '.jpg', '.jpeg'] else 'png'

            # 构建上下文信息
            context_info = ""
            figure_number = ""
            source_file = ""

            if metadata:
                parts = []

                # 提取文件来源
                source_file = metadata.get('source', '')
                if source_file:
                    parts.append(f"来源文档：{source_file}")

                # 检查是否为表格图片
                is_table = metadata.get('is_table', False)
                table_number = metadata.get('table_number', '')

                # 提取图号/表号（优先级：显式传递 > section 中提取 > caption 中提取）
                if is_table and table_number:
                    # 表格图片：使用表号
                    parts.append(f"表格编号：表{table_number}")
                elif metadata.get('figure_number'):
                    figure_number = metadata['figure_number']
                elif metadata.get('section'):
                    import re
                    # 根据类型提取编号
                    if is_table:
                        table_match = re.search(r'[见如]?表\s*(\d+\.?\d*)', metadata['section'])
                        if table_match:
                            table_number = table_match.group(1)
                    else:
                        fig_match = re.search(r'[见如]?图\s*(\d+\.?\d*)', metadata['section'])
                        if fig_match:
                            figure_number = fig_match.group(1)
                    parts.append(f"章节：{metadata['section']}")

                # 也从完整文档文本中提取编号
                doc_text = metadata.get('doc_text', '')
                if is_table and not table_number and doc_text:
                    import re
                    table_match = re.search(r'[见如]?表\s*(\d+\.?\d*)', doc_text)
                    if table_match:
                        table_number = table_match.group(1)
                elif not figure_number and doc_text:
                    import re
                    fig_match = re.search(r'[见如]?图\s*(\d+\.?\d*)', doc_text)
                    if fig_match:
                        figure_number = fig_match.group(1)

                if metadata.get('page'):
                    parts.append(f"第{metadata['page']}页")

                caption = metadata.get('caption', '')
                if caption and caption not in ('图片', '图表'):
                    parts.append(f"标题：{caption}")
                    # 从 caption 中提取图号
                    if not figure_number:
                        import re
                        fig_match = re.search(r'图\s*(\d+\.?\d*)', caption)
                        if fig_match:
                            figure_number = fig_match.group(1)

                if parts:
                    context_info = f"\n\n【已知上下文】\n" + "\n".join(parts)

            # 构建增强 prompt（区分图片和表格）
            if is_table and table_number:
                number_instruction = f"\n5. 这是表{table_number}，请在描述开头明确标注「表{table_number}」"
                prompt = f"""请分析这张表格图片并生成详细描述。

要求：
1. 这是表格图片，请识别表格结构和内容
2. 描述表格的主要数据、关键指标或统计信息
3. 如果表格有标题行，请说明表格主题
4. 输出格式：[表格] 主要内容描述{number_instruction}{context_info}

请直接输出描述，不超过150字。"""
            else:
                figure_instruction = ""
                if figure_number:
                    figure_instruction = f"\n5. 如果识别出这是图{figure_number}，请在描述开头明确标注「图{figure_number}」"

                prompt = f"""请分析这张图片并生成详细描述。

要求：
1. 识别图片类型（折线图、柱状图、流程图、示意图、表格图等）
2. 描述图片的主要内容、数据趋势或关键信息
3. 如果是数据图表，提取关键数值和趋势
4. 输出格式：[图片类型] 主要内容描述{figure_instruction}{context_info}

请直接输出描述，不超过150字。"""

            client = get_llm_client()

            # 使用视觉模型
            response = client.chat.completions.create(
                model=DASHSCOPE_VL_MODEL,  # 使用配置文件中的视觉模型
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/{image_format};base64,{image_data}"}}
                    ]
                }],
                max_tokens=300
            )

            content = response.choices[0].message.content
            if content:
                # 根据类型添加编号前缀
                if is_table and table_number:
                    # 表格图片
                    if f"表{table_number}" not in content:
                        content = f"表{table_number}：{content}"
                elif figure_number:
                    # 普通图片
                    if f"图{figure_number}" not in content:
                        content = f"图{figure_number}：{content}"
                # 如果有文件来源但描述中没有，在末尾添加
                if source_file and source_file not in content:
                    content = f"{content}（来源：{source_file}）"
                return content.strip()
            else:
                logger.warning("VLM 返回空内容")
                if is_table and table_number:
                    return f"表{table_number}：{os.path.basename(image_path)}（来源：{source_file}）" if source_file else f"表{table_number}：{os.path.basename(image_path)}"
                elif figure_number:
                    return f"图{figure_number}：{os.path.basename(image_path)}（来源：{source_file}）" if source_file else f"图{figure_number}：{os.path.basename(image_path)}"
                return f"图片：{os.path.basename(image_path)}"

        except Exception as e:
            logger.warning(f"图片描述生成失败: {e}")
            return f"图片：{os.path.basename(image_path)}"

    def _store_original_table(self, doc_id: str, table_md: str, metadata: dict):
        """
        存储原始表格到 DocStore

        Args:
            doc_id: 文档 ID
            table_md: 表格 Markdown 内容
            metadata: 元数据
        """
        try:
            import json
            from pathlib import Path

            # 使用文件系统作为 DocStore
            docstore_dir = Path(".data/docstore")
            docstore_dir.mkdir(parents=True, exist_ok=True)

            record = {
                "content_type": "table",
                "markdown": table_md,
                "meta": metadata
            }

            doc_path = docstore_dir / f"{doc_id}.json"
            with open(doc_path, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"存储原始表格失败: {e}")

    def _store_image_reference(self, doc_id: str, image_path: str, metadata: dict):
        """
        存储图片引用到 DocStore

        Args:
            doc_id: 文档 ID
            image_path: 图片路径
            metadata: 元数据
        """
        try:
            import json
            from pathlib import Path

            docstore_dir = Path(".data/docstore")
            docstore_dir.mkdir(parents=True, exist_ok=True)

            record = {
                "content_type": "image",
                "storage_type": "file",
                "file_path": image_path,
                "meta": metadata
            }

            doc_path = docstore_dir / f"{doc_id}.json"
            with open(doc_path, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"存储图片引用失败: {e}")

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
        use_bm25: bool = True,
        include_deprecated: bool = False
    ) -> Optional[SearchResult]:
        """
        单向量库检索

        Args:
            kb_name: 向量库名称
            query_vector: 查询向量
            query_text: 查询文本（用于 BM25）
            top_k: 返回数量
            use_bm25: 是否使用 BM25
            include_deprecated: 是否包含已废止/已替代的文档

        Returns:
            检索结果
        """
        collection = self.get_collection(kb_name)
        if not collection or collection.count() == 0:
            return None

        # 构建 where 过滤条件
        where_filter = None
        if not include_deprecated:
            where_filter = {"status": "active"}  # 只查询 active 状态

        # 向量检索（带状态过滤）
        vector_result = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where_filter  # 应用过滤
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

        # 如果不包含废止文档，需要过滤 BM25 结果
        if not include_deprecated and bm25_metas:
            filtered_bm25 = []
            for i, meta in enumerate(bm25_metas):
                if meta.get('status', 'active') == 'active':
                    filtered_bm25.append((bm25_ids[i], bm25_docs[i], bm25_metas[i], bm25_scores[i]))

            if filtered_bm25:
                bm25_ids, bm25_docs, bm25_metas, bm25_scores = zip(*filtered_bm25)
            else:
                bm25_ids, bm25_docs, bm25_metas, bm25_scores = [], [], [], []

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

    def mark_document_as_superseded(
        self,
        kb_name: str,
        filename: str,
        reason: str = "被新版本替代"
    ) -> Dict:
        """
        标记文档为已替代状态（软删除）

        Args:
            kb_name: 知识库名称
            filename: 文件名
            reason: 替代原因

        Returns:
            操作结果
        """
        from datetime import datetime

        collection = self.get_collection(kb_name)
        if not collection:
            return {"success": False, "message": "向量库不存在"}

        # 1. 查询该文件的所有 active chunks
        result = collection.get(
            where={
                "$and": [
                    {"source": filename},
                    {"status": "active"}
                ]
            }
        )

        if not result['ids']:
            logger.warning(f"未找到活跃文档: {kb_name}/{filename}")
            return {"success": False, "message": "未找到活跃文档"}

        # 2. 更新 metadata
        superseded_time = datetime.now().isoformat()
        updated_metadatas = [
            {
                **m,
                "status": "superseded",
                "superseded_time": superseded_time,
                "superseded_reason": reason
            }
            for m in result['metadatas']
        ]

        # 3. 批量更新
        collection.update(
            ids=result['ids'],
            metadatas=updated_metadatas
        )

        # 4. 重建 BM25 索引
        self.rebuild_bm25_index(kb_name)

        logger.info(f"标记文档为 superseded: {kb_name}/{filename}, chunks: {len(result['ids'])}")

        return {
            "success": True,
            "superseded_chunks": len(result['ids']),
            "document_id": filename,
            "collection": kb_name,
            "superseded_time": superseded_time
        }

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

        # 创建版本记录
        try:
            from knowledge.document_versions import get_version_query
            version_query = get_version_query()

            # 创建废止版本记录（自动生成版本号）
            version_query.create_version_record(
                collection=kb_name,
                document_id=filename,
                status="deprecated",
                change_summary=f"废止原因: {reason}",
                created_by=deprecated_by,
                chunk_count=len(result['ids'])
            )

            # 记录变更日志
            version_query.log_version_change(
                collection=kb_name,
                document_id=filename,
                change_type="deprecate",
                old_status="active",
                new_status="deprecated",
                reason=reason,
                changed_by=deprecated_by
            )
        except Exception as e:
            logger.warning(f"创建版本记录失败: {e}")

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

        # 创建版本记录
        try:
            from knowledge.document_versions import get_version_query
            version_query = get_version_query()

            # 创建恢复版本记录（自动生成版本号）
            version_query.create_version_record(
                collection=kb_name,
                document_id=filename,
                status="active",
                change_summary="文档已恢复",
                created_by="system",
                chunk_count=len(result['ids'])
            )

            # 记录变更日志
            version_query.log_version_change(
                collection=kb_name,
                document_id=filename,
                change_type="restore",
                old_status="deprecated",
                new_status="active",
                reason="文档恢复",
                changed_by="system"
            )
        except Exception as e:
            logger.warning(f"创建版本记录失败: {e}")

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
