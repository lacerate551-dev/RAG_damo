# -*- coding: utf-8 -*-
"""
文本分块模块

提供带硬性上限的分块函数，确保切片不会超过 max_length。

核心特性：
- 基于 LangChain RecursiveCharacterTextSplitter
- Markdown 结构感知分块
- 硬性上限保护（max_length=1000）
"""

from typing import List


def split_text_with_limit(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 100,
    max_length: int = 1000
) -> List[str]:
    """
    带硬性上限的分块函数

    确保切片不会超过 max_length，用于处理超长文本。

    Args:
        text: 待分块文本
        chunk_size: 目标分块大小
        overlap: 分块重叠字符数
        max_length: 硬性上限

    Returns:
        分块列表
    """
    if not text or not text.strip():
        return []

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")

    # Markdown 分隔符优先级
    separators = [
        "\n#{1,6} ",  # 标题
        "\n```\n",    # 代码块
        "\n|",        # 表格
        "\n\n",       # 段落
        "\n",         # 行
        " ",          # 词
        ""            # 字符
    ]

    splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
        keep_separator=True
    )

    chunks = splitter.split_text(text)

    # 硬性上限保护
    result = []
    for chunk in chunks:
        if len(chunk) > max_length:
            # 尝试在句子边界截断
            last_boundary = max(
                chunk.rfind('。', 0, max_length),
                chunk.rfind('？', 0, max_length),
                chunk.rfind('！', 0, max_length),
                chunk.rfind('.', 0, max_length),
                chunk.rfind('\n', 0, max_length)
            )
            if last_boundary > max_length // 2:
                result.append(chunk[:last_boundary + 1])
            else:
                result.append(chunk[:max_length])
        else:
            result.append(chunk)

    return result


# 兼容性别名
split_text = split_text_with_limit
