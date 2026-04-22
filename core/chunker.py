# -*- coding: utf-8 -*-
"""
文本分块模块

提供带硬性上限的分块函数，确保切片不会超过 max_length。

核心特性：
- 基于 LangChain RecursiveCharacterTextSplitter
- Markdown 结构感知分块
- 硬性上限保护（max_length=1200）
- 最小切片约束（min_length=200）
- 相邻切片合并（过短切片）
"""

from typing import List
import re


def split_text_with_limit(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 100,
    max_length: int = 1200,
    min_length: int = 200
) -> List[str]:
    """
    带硬性上限和下限的分块函数

    确保切片不会超过 max_length，且不会低于 min_length（尝试合并）。

    Args:
        text: 待分块文本
        chunk_size: 目标分块大小
        overlap: 分块重叠字符数
        max_length: 硬性上限
        min_length: 硬性下限（过短则尝试合并）

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

    # 第一轮：硬性上限保护
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

    # 第二轮：合并过短的切片
    result = merge_short_chunks(result, min_length, max_length)

    return result


def merge_short_chunks(chunks: List[str], min_length: int, max_length: int) -> List[str]:
    """
    合并过短的相邻切片

    Args:
        chunks: 原始切片列表
        min_length: 最小长度
        max_length: 最大长度

    Returns:
        合并后的切片列表
    """
    if not chunks or min_length <= 0:
        return chunks

    result = []
    i = 0

    while i < len(chunks):
        current = chunks[i]

        # 如果当前切片过短，尝试与下一个合并
        while len(current) < min_length and i + 1 < len(chunks):
            next_chunk = chunks[i + 1]
            merged = current + "\n" + next_chunk

            # 检查合并后是否超过上限
            if len(merged) <= max_length:
                current = merged
                i += 1
            else:
                # 合并后超限，停止合并
                break

        result.append(current)
        i += 1

    return result


def filter_chunks_by_section(
    chunks: List[dict],
    query: str,
    section_keywords: List[str] = None
) -> List[dict]:
    """
    根据查询中的章节信息过滤切片

    Args:
        chunks: 切片列表，每个切片需包含 metadata
        query: 用户查询
        section_keywords: 章节关键词列表

    Returns:
        过滤后的切片列表
    """
    if not section_keywords:
        section_keywords = [
            "第一章", "第二章", "第三章", "第四章", "第五章",
            "第1章", "第2章", "第3章", "第4章", "第5章",
            "一、", "二、", "三、", "四、", "五、",
            "1.", "2.", "3.", "4.", "5."
        ]

    # 从查询中提取章节关键词
    mentioned_sections = []
    for keyword in section_keywords:
        if keyword in query:
            mentioned_sections.append(keyword)

    if not mentioned_sections:
        return chunks

    # 过滤切片
    result = []
    for chunk in chunks:
        metadata = chunk.get('metadata', chunk)
        section_path = metadata.get('section', metadata.get('section_path', ''))

        # 检查是否匹配任一章节
        for section in mentioned_sections:
            if section in section_path or section in chunk.get('content', ''):
                result.append(chunk)
                break

    # 如果过滤后结果为空，返回原始列表
    return result if result else chunks


def extract_section_mention(query: str) -> str:
    """
    从查询中提取章节提及

    Args:
        query: 用户查询

    Returns:
        提取的章节字符串，如 "第一章"
    """
    patterns = [
        r'第[一二三四五六七八九十\d]+章',
        r'第\s*\d+\s*章',
        r'[一二三四五六七八九十]+、',
        r'\d+\.',
    ]

    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            return match.group()

    return ""


# 兼容性别名
split_text = split_text_with_limit


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    # 测试分块
    test_text = """
一、适用范围

适用于全省地市公司货源投放工作所涉及的基础工作。

二、总体要求

货源投放是烟草营销的核心业务，总体要求是：
1.坚持市场导向、供需匹配；
2.坚持总量控制、稍紧平衡。

三、投放方法

主要有六种投放方法。
"""

    print("=" * 60)
    print("分块测试")
    print("=" * 60)

    chunks = split_text_with_limit(test_text, chunk_size=100, min_length=50)
    for i, chunk in enumerate(chunks, 1):
        print(f"\n[{i}] (len={len(chunk)})")
        print(chunk.strip()[:100])

    print("\n" + "=" * 60)
    print("章节过滤测试")
    print("=" * 60)

    test_chunks = [
        {"content": "内容1", "metadata": {"section": "一、适用范围"}},
        {"content": "内容2", "metadata": {"section": "二、总体要求"}},
        {"content": "内容3", "metadata": {"section": "三、投放方法"}},
    ]

    filtered = filter_chunks_by_section(test_chunks, "适用范围是什么？")
    print(f"查询: '适用范围是什么？'")
    print(f"匹配结果: {[c['metadata']['section'] for c in filtered]}")
