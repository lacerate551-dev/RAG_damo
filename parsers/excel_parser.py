# -*- coding: utf-8 -*-
"""
Excel 解析模块（Pandas 管道）

MinerU 不支持 XLSX 格式，因此使用 Pandas 专属管道处理。

策略：表级摘要（Chroma）+ 完整 Markdown（DocStore）
- 每个 sheet 生成 Markdown 表格
- 大表（>200行）按行切片，每片保留表头
- 每片包装为 UnifiedChunk(type='table')

检索链路:
用户提问 → 命中摘要 → 拿 doc_id → 掏 Markdown → 喂 LLM
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# 大表切片阈值
MAX_ROWS_PER_CHUNK = 200


@dataclass
class UnifiedChunk:
    """统一内部 Schema - 与 MinerUChunk 兼容"""
    content: str                      # 文本内容（Markdown 格式）
    chunk_type: str                   # 类型: table
    page_start: int = 1               # 起始行号（Excel 无页码概念）
    page_end: int = 1                 # 结束行号
    text_level: int = 0               # 标题级别（Excel 无标题层级）
    title: str = ""                   # Sheet 名称
    section_path: str = ""            # 章节路径
    source_file: str = ""             # 源文件名
    bbox: Optional[List[float]] = field(default=None)  # 不适用
    table_html: Optional[str] = field(default=None)    # 表格 HTML（可选）
    image_path: Optional[str] = field(default=None)    # 不适用
    # Excel 专用元数据
    sheet_name: str = ""              # Sheet 名称
    row_start: int = 0                # 起始行（0-indexed）
    row_end: int = 0                  # 结束行
    col_count: int = 0                # 列数
    headers: List[str] = field(default_factory=list)   # 表头列表


def parse_excel(
    filepath: str,
    max_rows_per_chunk: int = MAX_ROWS_PER_CHUNK
) -> Dict[str, Any]:
    """
    解析 Excel 文件，输出 UnifiedChunk 列表

    Args:
        filepath: Excel 文件路径
        max_rows_per_chunk: 大表切片阈值，默认 200 行

    Returns:
        {
            'chunks': List[UnifiedChunk],  # 结构化分块
            'sheets': List[str],           # Sheet 名称列表
            'total_rows': int,             # 总行数
            'source_file': str             # 源文件名
        }
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    logger.info(f"使用 Pandas 解析 Excel: {filepath.name}")

    chunks = []
    sheet_names = []
    total_rows = 0

    # 读取所有 sheets
    try:
        xls = pd.ExcelFile(filepath)
        sheet_names = xls.sheet_names
    except Exception as e:
        raise RuntimeError(f"Excel 文件读取失败: {e}")

    for sheet_name in sheet_names:
        try:
            # 先读取原始数据（不指定表头）
            df_raw = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
        except Exception as e:
            logger.warning(f"Sheet '{sheet_name}' 读取失败: {e}")
            continue

        if df_raw.empty:
            logger.debug(f"Sheet '{sheet_name}' 为空，跳过")
            continue

        # 清理数据：填充 NaN
        df_raw = df_raw.fillna('')

        # 检测表头行（查找包含"部门"、"负责人"等典型表头关键词的行）
        header_row_idx = _detect_header_row(df_raw)

        # 提取表格标题（表头上方的行）
        table_title = ""
        if header_row_idx > 0:
            # 表头上方的第一行可能是标题
            first_row = df_raw.iloc[0]
            first_row_text = ' '.join([str(v) for v in first_row if str(v).strip()])
            if first_row_text and len(first_row_text) < 50:
                table_title = first_row_text

        # 重新读取，使用检测到的表头行
        if header_row_idx is not None and header_row_idx > 0:
            df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row_idx)
        else:
            df = pd.read_excel(filepath, sheet_name=sheet_name)

        df = df.fillna('')

        row_count = len(df)
        col_count = len(df.columns)
        total_rows += row_count

        # 获取表头
        headers = [str(col) for col in df.columns.tolist()]

        # 过滤掉 Unnamed 列名
        headers = [h if not h.startswith('Unnamed') else f'列{i+1}' for i, h in enumerate(headers)]

        # 大表切片
        if row_count > max_rows_per_chunk:
            logger.info(f"Sheet '{sheet_name}' 有 {row_count} 行，按 {max_rows_per_chunk} 行切片")

            num_chunks = (row_count + max_rows_per_chunk - 1) // max_rows_per_chunk

            for i in range(num_chunks):
                start_row = i * max_rows_per_chunk
                end_row = min((i + 1) * max_rows_per_chunk, row_count)

                # 切片数据（保留表头）
                df_slice = df.iloc[start_row:end_row]

                # 转 Markdown
                md_table = _df_to_markdown(df_slice, headers)

                # 标注切片信息
                chunk_title = f"{sheet_name} (第{i+1}/{num_chunks}片，行{start_row+1}-{end_row})"

                chunk = UnifiedChunk(
                    content=md_table,
                    chunk_type="table",
                    page_start=start_row + 1,
                    page_end=end_row,
                    title=chunk_title,
                    section_path=sheet_name,
                    source_file=filepath.name,
                    sheet_name=sheet_name,
                    row_start=start_row,
                    row_end=end_row,
                    col_count=col_count,
                    headers=headers
                )
                chunks.append(chunk)
        else:
            # 小表直接转换
            md_table = _df_to_markdown(df, headers)

            # 使用表格标题或 sheet 名称
            chunk_title = table_title if table_title else sheet_name

            chunk = UnifiedChunk(
                content=md_table,
                chunk_type="table",
                page_start=1,
                page_end=row_count,
                title=chunk_title,
                section_path=sheet_name,
                source_file=filepath.name,
                sheet_name=sheet_name,
                row_start=0,
                row_end=row_count,
                col_count=col_count,
                headers=headers
            )
            chunks.append(chunk)

    logger.info(f"Excel 解析完成: {len(chunks)} 个表格块，{total_rows} 行数据")

    return {
        'chunks': chunks,
        'sheets': sheet_names,
        'total_rows': total_rows,
        'source_file': filepath.name
    }


def _detect_header_row(df: pd.DataFrame) -> Optional[int]:
    """
    检测表头行位置

    表头特征：
    1. 包含典型表头关键词（部门、负责人、名称、数量等）
    2. 不含大量数字（数据行特征）
    3. 文本较短

    Returns:
        表头行索引（0-indexed），未找到返回 0
    """
    # 典型表头关键词
    header_keywords = {
        '部门', '负责人', '名称', '数量', '人数', '金额', '日期', '地址',
        '电话', '邮箱', '编号', '类型', '状态', '备注', '描述', '职位',
        '团队', '职责', '地点', '公司', '分', '总', '规模', '职能'
    }

    best_row = 0
    best_score = 0

    for idx in range(min(5, len(df))):  # 只检查前 5 行
        row = df.iloc[idx]
        score = 0

        for cell in row:
            cell_str = str(cell).strip()
            if not cell_str:
                continue

            # 检查关键词
            for kw in header_keywords:
                if kw in cell_str:
                    score += 2

            # 短文本倾向于表头
            if len(cell_str) < 20:
                score += 1

            # 数字倾向于数据行
            try:
                float(cell_str)
                score -= 3
            except ValueError:
                pass

        if score > best_score:
            best_score = score
            best_row = idx

    return best_row


def _df_to_markdown(df: pd.DataFrame, headers: List[str] = None) -> str:
    """
    将 DataFrame 转换为 Markdown 表格格式

    Args:
        df: DataFrame
        headers: 表头列表（可选，默认使用 df.columns）

    Returns:
        Markdown 表格字符串
    """
    if headers is None:
        headers = [str(col) for col in df.columns.tolist()]

    lines = []

    # 表头行
    header_line = "| " + " | ".join(headers) + " |"
    lines.append(header_line)

    # 分隔行
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    lines.append(separator)

    # 数据行
    for _, row in df.iterrows():
        cells = [str(val).replace('\n', ' ').replace('|', '\\|') for val in row]
        data_line = "| " + " | ".join(cells) + " |"
        lines.append(data_line)

    return "\n".join(lines)


def get_table_meta(filepath: str, sheet_name: str = None) -> Dict[str, Any]:
    """
    获取 Excel 表格元数据（供 LLM 摘要使用）

    Args:
        filepath: Excel 文件路径
        sheet_name: Sheet 名称（可选，默认第一个 sheet）

    Returns:
        {
            'sheet_name': str,
            'columns': List[str],
            'row_count': int,
            'col_count': int,
            'sample_rows': List[Dict],  # 前 5 行数据
        }
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    xls = pd.ExcelFile(filepath)

    if sheet_name is None:
        sheet_name = xls.sheet_names[0]

    df = pd.read_excel(filepath, sheet_name=sheet_name)
    df = df.fillna('')

    columns = [str(col) for col in df.columns.tolist()]
    row_count = len(df)
    col_count = len(df.columns)

    # 前 5 行样本
    sample_df = df.head(5)
    sample_rows = sample_df.to_dict(orient='records')

    return {
        'sheet_name': sheet_name,
        'columns': columns,
        'row_count': row_count,
        'col_count': col_count,
        'sample_rows': sample_rows
    }


def convert_to_rag_format(result: Dict[str, Any]) -> List[Dict]:
    """
    将 Excel 解析结果转换为 RAG 入库格式

    Args:
        result: parse_excel() 返回结果

    Returns:
        [{'text': ..., 'page': ..., 'has_table': True, ...}, ...]
    """
    pages_content = []

    for chunk in result['chunks']:
        # 构建内容文本
        content = f"【表格】{chunk.title}\n\n{chunk.content}"

        page_info = {
            'text': content,
            'page': chunk.page_start,
            'page_end': chunk.page_end,
            'has_table': True,
            'section': chunk.title,
            'section_path': chunk.section_path,
            'level': 0,
            'chunk_type': 'table',
            'source_file': chunk.source_file,
            'is_excel_chunk': True,  # 标记为 Excel 输出
            # Excel 专用元数据
            'sheet_name': chunk.sheet_name,
            'row_start': chunk.row_start,
            'row_end': chunk.row_end,
            'col_count': chunk.col_count,
        }

        pages_content.append(page_info)

    return pages_content


# ========== 兼容旧接口 ==========

def parse_xlsx_enhanced(filepath: str) -> Dict[str, Any]:
    """
    兼容旧接口：使用增强解析器处理 Excel 文件

    Args:
        filepath: Excel 文件路径

    Returns:
        解析结果（兼容旧格式）
    """
    result = parse_excel(filepath)

    # 转换为旧格式
    chunks = []
    for chunk in result['chunks']:
        chunks.append({
            'content': chunk.content,
            'title': chunk.title,
            'sheet': chunk.sheet_name,
            'row_range': f"{chunk.row_start+1}-{chunk.row_end}",
            'col_range': f"A-{chr(64+chunk.col_count)}" if chunk.col_count <= 26 else "A-...",
            'chunk_type': chunk.chunk_type,
            'headers': chunk.headers,
            'source_file': chunk.source_file,
            'metadata': {
                'row_count': chunk.row_end - chunk.row_start,
                'col_count': chunk.col_count
            }
        })

    return {
        'chunks': chunks,
        'sheets': [{'name': s, 'rows': 0, 'cols': 0} for s in result['sheets']],
        'metadata': {
            'source_file': result['source_file'],
            'total_chunks': len(chunks)
        }
    }


def get_excel_chunks_for_rag(
    filepath: str,
    min_chunk_size: int = 50
) -> tuple:
    """
    兼容旧接口：获取适合 RAG 系统的 Excel 分块

    Args:
        filepath: 文件路径
        min_chunk_size: 最小分块大小

    Returns:
        (documents, metadatas) - 文档列表和元数据列表
    """
    result = parse_excel(filepath)

    documents = []
    metadatas = []

    for chunk in result['chunks']:
        if len(chunk.content.strip()) >= min_chunk_size:
            documents.append(chunk.content)
            metadatas.append({
                'title': chunk.title,
                'sheet': chunk.sheet_name,
                'row_range': f"{chunk.row_start+1}-{chunk.row_end}",
                'col_count': chunk.col_count,
                'chunk_type': chunk.chunk_type,
                'source_file': chunk.source_file
            })

    return documents, metadatas


if __name__ == "__main__":
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("用法: python excel_parser.py <Excel文件路径>")
        sys.exit(1)

    file_path = sys.argv[1]

    print(f"正在解析: {file_path}")
    result = parse_excel(file_path)

    print(f"\n解析完成:")
    print(f"- Sheets: {result['sheets']}")
    print(f"- 总行数: {result['total_rows']}")
    print(f"- 表格块数: {len(result['chunks'])}")

    # 显示每个块的信息
    print("\n表格块详情:")
    for i, chunk in enumerate(result['chunks']):
        print(f"\n--- Chunk {i+1} ---")
        print(f"Sheet: {chunk.sheet_name}")
        print(f"行范围: {chunk.row_start+1} - {chunk.row_end}")
        print(f"列数: {chunk.col_count}")
        preview = chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
        print(f"内容预览: {preview}")
