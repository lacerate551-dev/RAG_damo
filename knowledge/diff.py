"""
Chunk级别差异检测 - 支持增量更新

功能：
1. 文档差异分析 - 比较新旧文档的chunks差异
2. 增量更新策略 - 识别added/deleted/modified/unchanged chunks
3. 影响评估 - 分析变更对题目的影响级别

使用方式：
    from document_diff import DocumentDiffAnalyzer, ChunkDiff

    analyzer = DocumentDiffAnalyzer()

    # 计算差异
    diff_result = analyzer.compute_diff(old_chunks, new_chunks)

    # 分析影响
    impact = analyzer.analyze_impact(diff_result)
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import numpy as np

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 数据类 ====================

@dataclass
class ChunkDiff:
    """单个Chunk的差异信息"""
    chunk_id: str
    diff_type: str              # 'added', 'deleted', 'modified', 'unchanged'
    similarity: float = 0.0     # 相似度 (0-1)
    old_content: str = ""       # 旧内容（仅modified/deleted有）
    new_content: str = ""       # 新内容（仅modified/added有）
    old_metadata: Dict = field(default_factory=dict)
    new_metadata: Dict = field(default_factory=dict)
    position_old: int = -1      # 旧文档中的位置
    position_new: int = -1      # 新文档中的位置


@dataclass
class DiffResult:
    """差异检测结果"""
    added: List[str] = field(default_factory=list)          # 新增的chunk IDs
    deleted: List[str] = field(default_factory=list)        # 删除的chunk IDs
    modified: List[Dict] = field(default_factory=list)      # 修改的chunks [{old_id, new_id, similarity}]
    unchanged: List[str] = field(default_factory=list)      # 未变的chunk IDs

    added_count: int = 0
    deleted_count: int = 0
    modified_count: int = 0
    unchanged_count: int = 0

    impact_level: str = "none"       # high/medium/low/none
    impact_message: str = ""

    # 详细信息
    details: List[ChunkDiff] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "added": self.added,
            "deleted": self.deleted,
            "modified": self.modified,
            "unchanged": self.unchanged,
            "added_count": self.added_count,
            "deleted_count": self.deleted_count,
            "modified_count": self.modified_count,
            "unchanged_count": self.unchanged_count,
            "impact_level": self.impact_level,
            "impact_message": self.impact_message
        }


# ==================== 差异分析器 ====================

class DocumentDiffAnalyzer:
    """
    文档差异分析器

    比较新旧文档的chunks，识别变更类型，
    评估变更对题目的影响级别。
    """

    # 相似度阈值
    SIMILARITY_THRESHOLD = 0.85    # 认为是同一chunk的阈值
    UNCHANGED_THRESHOLD = 0.99     # 认为完全相同的阈值
    HIGH_IMPACT_THRESHOLD = 0.3    # 高影响变更比例阈值

    def __init__(self, embedding_model=None):
        """
        初始化

        Args:
            embedding_model: 向量模型（可选，用于相似度计算）
        """
        self.embedding_model = embedding_model
        self._init_embedding_model()

    def _init_embedding_model(self):
        """初始化向量模型"""
        if self.embedding_model is not None:
            return

        try:
            from rag_demo import embedding_model
            self.embedding_model = embedding_model
            logger.info("使用 rag_demo 的向量模型")
        except ImportError:
            pass

        if self.embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.embedding_model = SentenceTransformer('BAAI/bge-base-zh-v1.5')
                logger.info("加载本地向量模型成功")
            except Exception as e:
                logger.warning(f"无法加载向量模型: {e}")

    def compute_diff(
        self,
        old_chunks: List[Dict],
        new_chunks: List[Dict]
    ) -> DiffResult:
        """
        计算Chunk级别差异

        算法：
        1. Hash精确匹配 - 快速识别完全相同的chunks
        2. 向量相似度匹配 - 识别内容相似的chunks
        3. 分类 - added/deleted/modified/unchanged

        Args:
            old_chunks: 旧文档chunks列表，每个元素包含：
                - id: chunk ID
                - content: 文本内容
                - embedding: 向量（可选）
                - metadata: 元数据
            new_chunks: 新文档chunks列表

        Returns:
            DiffResult 差异结果
        """
        result = DiffResult()
        details = []

        # 边界情况
        if not old_chunks and not new_chunks:
            return result

        if not old_chunks:
            result.added = [c.get('id', f'new_{i}') for i, c in enumerate(new_chunks)]
            result.added_count = len(result.added)
            result.impact_level = "high"
            result.impact_message = "新增文档"
            return result

        if not new_chunks:
            result.deleted = [c.get('id', f'old_{i}') for i, c in enumerate(old_chunks)]
            result.deleted_count = len(result.deleted)
            result.impact_level = "high"
            result.impact_message = "文档已删除"
            return result

        # Step 1: Hash精确匹配
        old_hash_map = {}
        for i, c in enumerate(old_chunks):
            content = c.get('content', '')
            h = self._hash(content)
            if h not in old_hash_map:
                old_hash_map[h] = []
            old_hash_map[h].append({**c, 'position': i})

        new_hash_map = {}
        for i, c in enumerate(new_chunks):
            content = c.get('content', '')
            h = self._hash(content)
            if h not in new_hash_map:
                new_hash_map[h] = []
            new_hash_map[h].append({**c, 'position': i})

        # 完全相同的chunks
        common_hashes = set(old_hash_map.keys()) & set(new_hash_map.keys())
        matched_old = set()
        matched_new = set()

        for h in common_hashes:
            old_list = old_hash_map[h]
            new_list = new_hash_map[h]

            # 一一匹配
            for old_c in old_list:
                for new_c in new_list:
                    new_id = new_c.get('id')
                    if new_id in matched_new:
                        continue

                    result.unchanged.append(old_c.get('id'))
                    matched_old.add(old_c.get('id'))
                    matched_new.add(new_id)

                    details.append(ChunkDiff(
                        chunk_id=old_c.get('id'),
                        diff_type='unchanged',
                        similarity=1.0,
                        old_content=old_c.get('content', ''),
                        new_content=new_c.get('content', ''),
                        position_old=old_c.get('position', -1),
                        position_new=new_c.get('position', -1)
                    ))
                    break

        # Step 2: 剩余chunks用向量相似度匹配
        remaining_old = [c for c in old_chunks if c.get('id') not in matched_old]
        remaining_new = [c for c in new_chunks if c.get('id') not in matched_new]

        if remaining_old and remaining_new and self.embedding_model:
            self._match_by_similarity(
                remaining_old, remaining_new,
                matched_old, matched_new,
                result, details
            )

        # Step 3: 未匹配的分类
        for c in remaining_old:
            if c.get('id') not in matched_old:
                result.deleted.append(c.get('id'))
                details.append(ChunkDiff(
                    chunk_id=c.get('id'),
                    diff_type='deleted',
                    old_content=c.get('content', ''),
                    position_old=c.get('position', -1)
                ))

        for c in remaining_new:
            if c.get('id') not in matched_new:
                result.added.append(c.get('id'))
                details.append(ChunkDiff(
                    chunk_id=c.get('id'),
                    diff_type='added',
                    new_content=c.get('content', ''),
                    position_new=c.get('position', -1)
                ))

        # Step 4: 统计
        result.added_count = len(result.added)
        result.deleted_count = len(result.deleted)
        result.modified_count = len(result.modified)
        result.unchanged_count = len(result.unchanged)
        result.details = details

        # Step 5: 影响评估
        impact = self.analyze_impact(result)
        result.impact_level = impact['level']
        result.impact_message = impact['message']

        logger.info(
            f"差异检测完成: added={result.added_count}, "
            f"deleted={result.deleted_count}, modified={result.modified_count}, "
            f"unchanged={result.unchanged_count}, impact={result.impact_level}"
        )

        return result

    def _match_by_similarity(
        self,
        remaining_old: List[Dict],
        remaining_new: List[Dict],
        matched_old: set,
        matched_new: set,
        result: DiffResult,
        details: List[ChunkDiff]
    ):
        """使用向量相似度匹配剩余chunks"""
        # 获取embeddings
        old_embeddings = []
        for c in remaining_old:
            emb = c.get('embedding')
            if emb is None:
                # 计算embedding
                content = c.get('content', '')
                if content and self.embedding_model:
                    emb = self.embedding_model.encode(content).tolist()
            old_embeddings.append(emb)

        new_embeddings = []
        for c in remaining_new:
            emb = c.get('embedding')
            if emb is None:
                content = c.get('content', '')
                if content and self.embedding_model:
                    emb = self.embedding_model.encode(content).tolist()
            new_embeddings.append(emb)

        # 如果无法获取embeddings，使用简单的文本相似度
        if None in old_embeddings or None in new_embeddings:
            self._match_by_text_similarity(
                remaining_old, remaining_new,
                matched_old, matched_new,
                result, details
            )
            return

        # 计算相似度矩阵
        for i, (old_c, old_emb) in enumerate(zip(remaining_old, old_embeddings)):
            if old_c.get('id') in matched_old:
                continue

            best_match = None
            best_similarity = 0

            for j, (new_c, new_emb) in enumerate(zip(remaining_new, new_embeddings)):
                if new_c.get('id') in matched_new:
                    continue

                sim = self._cosine_similarity(old_emb, new_emb)

                if sim > best_similarity:
                    best_similarity = sim
                    best_match = new_c

            if best_match and best_similarity >= self.SIMILARITY_THRESHOLD:
                # 找到匹配
                if best_similarity >= self.UNCHANGED_THRESHOLD:
                    result.unchanged.append(old_c.get('id'))
                    diff_type = 'unchanged'
                else:
                    result.modified.append({
                        'old_id': old_c.get('id'),
                        'new_id': best_match.get('id'),
                        'similarity': best_similarity
                    })
                    diff_type = 'modified'

                matched_old.add(old_c.get('id'))
                matched_new.add(best_match.get('id'))

                details.append(ChunkDiff(
                    chunk_id=old_c.get('id'),
                    diff_type=diff_type,
                    similarity=best_similarity,
                    old_content=old_c.get('content', ''),
                    new_content=best_match.get('content', ''),
                    position_old=old_c.get('position', -1),
                    position_new=best_match.get('position', -1)
                ))

    def _match_by_text_similarity(
        self,
        remaining_old: List[Dict],
        remaining_new: List[Dict],
        matched_old: set,
        matched_new: set,
        result: DiffResult,
        details: List[ChunkDiff]
    ):
        """使用文本相似度匹配（fallback）"""
        for old_c in remaining_old:
            if old_c.get('id') in matched_old:
                continue

            old_content = old_c.get('content', '')
            best_match = None
            best_similarity = 0

            for new_c in remaining_new:
                if new_c.get('id') in matched_new:
                    continue

                new_content = new_c.get('content', '')
                sim = self._text_similarity(old_content, new_content)

                if sim > best_similarity:
                    best_similarity = sim
                    best_match = new_c

            if best_match and best_similarity >= self.SIMILARITY_THRESHOLD:
                result.modified.append({
                    'old_id': old_c.get('id'),
                    'new_id': best_match.get('id'),
                    'similarity': best_similarity
                })
                matched_old.add(old_c.get('id'))
                matched_new.add(best_match.get('id'))

                details.append(ChunkDiff(
                    chunk_id=old_c.get('id'),
                    diff_type='modified',
                    similarity=best_similarity,
                    old_content=old_content,
                    new_content=best_match.get('content', ''),
                    position_old=old_c.get('position', -1),
                    position_new=best_match.get('position', -1)
                ))

    def analyze_impact(self, diff_result: DiffResult) -> Dict:
        """
        分析变更影响级别

        Args:
            diff_result: 差异结果

        Returns:
            {
                "level": "high/medium/low/none",
                "message": "影响描述"
            }
        """
        total = (
            diff_result.added_count +
            diff_result.deleted_count +
            diff_result.modified_count +
            diff_result.unchanged_count
        )

        if total == 0:
            return {"level": "none", "message": "无内容"}

        changes = diff_result.added_count + diff_result.deleted_count + diff_result.modified_count
        change_ratio = changes / total

        # 高影响：有删除内容或变更比例超过30%
        if diff_result.deleted_count > 0:
            return {
                "level": "high",
                "message": f"删除了 {diff_result.deleted_count} 个内容片段，相关题目可能无效，需要审核"
            }

        if change_ratio >= self.HIGH_IMPACT_THRESHOLD:
            return {
                "level": "high",
                "message": f"大量内容变更（{changes}/{total}），相关题目可能无效，需要审核"
            }

        # 中等影响：有修改内容
        if diff_result.modified_count > 3:
            return {
                "level": "medium",
                "message": f"修改了 {diff_result.modified_count} 个内容片段，答案可能需要更新"
            }

        if diff_result.modified_count > 0:
            return {
                "level": "medium",
                "message": f"修改了 {diff_result.modified_count} 个内容片段，建议检查答案"
            }

        # 低影响：只有新增
        if diff_result.added_count > 0:
            return {
                "level": "low",
                "message": f"新增了 {diff_result.added_count} 个内容片段，建议检查是否需要补充新题"
            }

        return {"level": "none", "message": "无变化"}

    # ==================== 工具方法 ====================

    @staticmethod
    def _hash(content: str) -> str:
        """计算内容hash"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """简单的文本相似度（Jaccard）"""
        if not text1 or not text2:
            return 0.0

        # 分词
        try:
            import jieba
            words1 = set(jieba.cut(text1))
            words2 = set(jieba.cut(text2))
        except ImportError:
            # 简单按字符分割
            words1 = set(text1)
            words2 = set(text2)

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)


# ==================== 全局实例 ====================

_diff_analyzer: Optional[DocumentDiffAnalyzer] = None


def get_diff_analyzer() -> DocumentDiffAnalyzer:
    """获取全局差异分析器实例"""
    global _diff_analyzer
    if _diff_analyzer is None:
        _diff_analyzer = DocumentDiffAnalyzer()
    return _diff_analyzer
