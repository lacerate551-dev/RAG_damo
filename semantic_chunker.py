# -*- coding: utf-8 -*-
"""
语义分块模块

基于句子语义相似度进行智能分块，替代固定字符切分。
核心思想：相邻句子语义相似度突变处作为分块边界。

优势：
- 分块更符合语义边界，减少信息缺失
- 自动适应不同文档的语义结构
- 可与现有向量模型配合使用
"""

from typing import List, Dict, Optional, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer
import re
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SemanticChunker:
    """
    语义分块器 - 基于语义相似度确定分块边界

    工作原理：
    1. 将文本按句子分割
    2. 计算每个句子的向量表示
    3. 计算相邻句子的语义距离（1 - 相似度）
    4. 在语义距离突变处设置分块边界
    5. 合并句子形成最终分块

    使用示例：
    >>> from sentence_transformers import SentenceTransformer
    >>> model = SentenceTransformer("BAAI/bge-base-zh-v1.5")
    >>> chunker = SemanticChunker(model)
    >>> chunks = chunker.split_text("长文本内容...")
    """

    def __init__(
        self,
        embedding_model: SentenceTransformer,
        breakpoint_threshold: float = 0.5,
        min_chunk_size: int = 50,
        max_chunk_size: int = 800,
        sentence_batch_size: int = 100
    ):
        """
        初始化语义分块器

        Args:
            embedding_model: 向量模型，用于计算句子向量
            breakpoint_threshold: 分块阈值（百分位数），值越大分块越少
            min_chunk_size: 最小分块字符数
            max_chunk_size: 最大分块字符数
            sentence_batch_size: 批量处理句子数
        """
        self.embedding_model = embedding_model
        self.breakpoint_threshold = breakpoint_threshold
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.sentence_batch_size = sentence_batch_size

    def split_text(self, text: str) -> List[str]:
        """
        将文本按语义边界分块

        Args:
            text: 待分块的文本

        Returns:
            分块列表
        """
        if not text or not text.strip():
            return []

        # 1. 按句子分割
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            return [text.strip()] if text.strip() else []

        # 2. 计算句子向量
        try:
            embeddings = self.embedding_model.encode(
                sentences,
                batch_size=self.sentence_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True
            )
        except Exception as e:
            logger.warning(f"向量计算失败，使用简单分块: {e}")
            return self._fallback_split(text)

        # 3. 计算相邻句子语义距离
        distances = self._calculate_distances(embeddings)

        # 4. 确定分块边界
        breakpoints = self._find_breakpoints(distances, sentences)

        # 5. 合并句子为分块
        chunks = self._merge_sentences(sentences, breakpoints)

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        """
        按句子分割文本

        支持中英文句子边界识别
        """
        # 综合中英文句子分割模式
        # 中文：。！？
        # 英文：. ! ? (后跟空格或换行)
        # 通用：换行符
        pattern = r'(?<=[。！？\.!\?])\s*(?=[^\s])|(?<=\n)(?=[^\n])'

        sentences = re.split(pattern, text)

        # 过滤空句子并清理
        cleaned = []
        for s in sentences:
            s = s.strip()
            if s:
                cleaned.append(s)

        return cleaned

    def _calculate_distances(self, embeddings: np.ndarray) -> List[float]:
        """
        计算相邻句子的语义距离

        使用余弦距离：distance = 1 - cosine_similarity
        """
        distances = []
        for i in range(len(embeddings) - 1):
            # 计算余弦相似度
            vec1 = embeddings[i]
            vec2 = embeddings[i + 1]

            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                # 零向量，设置最大距离
                distances.append(1.0)
                continue

            similarity = np.dot(vec1, vec2) / (norm1 * norm2)
            # 转换为距离
            distance = 1 - similarity
            distances.append(float(distance))

        return distances

    def _find_breakpoints(
        self,
        distances: List[float],
        sentences: List[str]
    ) -> List[int]:
        """
        找到分块边界点

        边界条件：
        1. 语义距离超过阈值
        2. 累积长度超过最大限制
        """
        if not distances:
            return []

        # 计算动态阈值（基于百分位数）
        threshold = np.percentile(distances, self.breakpoint_threshold * 100)

        breakpoints = []
        current_length = 0

        for i, dist in enumerate(distances):
            # 当前句子长度
            sent_len = len(sentences[i])
            current_length += sent_len

            # 判断是否需要分块
            need_break = False

            # 条件1：语义距离超过阈值
            if dist > threshold:
                need_break = True

            # 条件2：累积长度超过最大限制
            if current_length >= self.max_chunk_size:
                need_break = True

            # 条件3：确保最小分块大小
            if need_break and current_length >= self.min_chunk_size:
                breakpoints.append(i + 1)
                current_length = 0
            elif need_break and current_length < self.min_chunk_size:
                # 长度不足，继续累积
                pass

        return breakpoints

    def _merge_sentences(
        self,
        sentences: List[str],
        breakpoints: List[int]
    ) -> List[str]:
        """
        合并句子为分块
        """
        if not sentences:
            return []

        chunks = []
        start = 0

        for bp in sorted(set(breakpoints)):
            if bp > start and bp <= len(sentences):
                chunk = ''.join(sentences[start:bp])
                if chunk.strip():
                    chunks.append(chunk.strip())
                start = bp

        # 处理最后一个分块
        if start < len(sentences):
            chunk = ''.join(sentences[start:])
            if chunk.strip():
                chunks.append(chunk.strip())

        return chunks

    def _fallback_split(self, text: str) -> List[str]:
        """
        降级分块策略（当向量计算失败时）
        """
        # 简单按段落分割
        paragraphs = text.split('\n\n')
        chunks = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(para) <= self.max_chunk_size:
                chunks.append(para)
            else:
                # 超长段落按句子分割
                sentences = self._split_sentences(para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) <= self.max_chunk_size:
                        current += sent
                    else:
                        if current:
                            chunks.append(current)
                        current = sent
                if current:
                    chunks.append(current)

        return chunks


class HybridChunker:
    """
    混合分块器 - 结合语义分块和结构分块

    适用于有明确结构的文档（如 Markdown）
    """

    def __init__(
        self,
        semantic_chunker: SemanticChunker,
        respect_headers: bool = True
    ):
        """
        Args:
            semantic_chunker: 语义分块器实例
            respect_headers: 是否在标题处强制分块
        """
        self.semantic_chunker = semantic_chunker
        self.respect_headers = respect_headers

    def split_text(self, text: str) -> List[str]:
        """
        混合分块：先按结构分割，再在每个结构块内进行语义分块
        """
        if self.respect_headers:
            # 按标题分割
            sections = self._split_by_headers(text)

            # 对每个 section 进行语义分块
            all_chunks = []
            for section in sections:
                if len(section) <= self.semantic_chunker.min_chunk_size:
                    if section.strip():
                        all_chunks.append(section.strip())
                else:
                    chunks = self.semantic_chunker.split_text(section)
                    all_chunks.extend(chunks)

            return all_chunks
        else:
            return self.semantic_chunker.split_text(text)

    def _split_by_headers(self, text: str) -> List[str]:
        """按 Markdown 标题分割"""
        # 匹配 Markdown 标题
        pattern = r'(?=^#{1,6}\s)'

        lines = text.split('\n')
        sections = []
        current_section = []

        for line in lines:
            if re.match(r'^#{1,6}\s', line) and current_section:
                # 遇到新标题，保存当前 section
                sections.append('\n'.join(current_section))
                current_section = [line]
            else:
                current_section.append(line)

        # 保存最后一个 section
        if current_section:
            sections.append('\n'.join(current_section))

        return sections


def create_semantic_chunker(
    model_path: str = "./models/bge-base-zh-v1.5",
    breakpoint_threshold: float = 0.5,
    min_chunk_size: int = 50,
    max_chunk_size: int = 800
) -> SemanticChunker:
    """
    便捷函数：创建语义分块器

    Args:
        model_path: 向量模型路径
        breakpoint_threshold: 分块阈值
        min_chunk_size: 最小分块字符数
        max_chunk_size: 最大分块字符数

    Returns:
        SemanticChunker 实例
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_path)
    return SemanticChunker(
        embedding_model=model,
        breakpoint_threshold=breakpoint_threshold,
        min_chunk_size=min_chunk_size,
        max_chunk_size=max_chunk_size
    )


if __name__ == "__main__":
    # 测试代码
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    # 示例文本
    sample_text = """
    人工智能是计算机科学的一个分支，它企图了解智能的实质，并生产出一种新的能以人类智能相似的方式做出反应的智能机器。

    人工智能研究的主要目标包括推理、知识、规划、学习、自然语言处理、感知和操作物体的能力。人工智能的发展经历了几个重要阶段。

    第一阶段是符号主义时期，研究者试图通过符号运算来模拟人类思维。第二阶段是连接主义时期，神经网络开始兴起。

    机器学习是人工智能的核心技术之一。它使计算机能够从数据中学习，而无需显式编程。深度学习是机器学习的一个子集，使用多层神经网络来处理复杂的模式识别任务。

    自然语言处理是人工智能的重要应用领域。它涉及计算机与人类语言之间的交互，包括文本理解、机器翻译、情感分析等任务。
    """

    print("测试语义分块器")
    print("=" * 50)

    # 创建分块器（需要模型）
    try:
        chunker = create_semantic_chunker(
            model_path="./models/bge-base-zh-v1.5",
            breakpoint_threshold=0.5
        )

        chunks = chunker.split_text(sample_text)

        print(f"\n分块结果: {len(chunks)} 个分块")
        for i, chunk in enumerate(chunks):
            print(f"\n--- 分块 {i+1} ({len(chunk)} 字符) ---")
            print(chunk[:100] + "..." if len(chunk) > 100 else chunk)

    except Exception as e:
        print(f"测试失败: {e}")
        print("请确保向量模型已下载到 ./models/bge-base-zh-v1.5")
