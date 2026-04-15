# -*- coding: utf-8 -*-
"""
Docling 文档解析模块

使用 Docling 统一解析多种文档格式：
- Word (.docx)
- Excel (.xlsx)
- PDF（补充 OpenDataLoader）
- HTML、TXT 等

优势：
- 保留文档结构（标题、段落、表格）
- 统一的输出格式
- 与 LangChain/LlamaIndex 集成
"""

import os
import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import logging

# 配置日志
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# 检查 Docling 是否可用
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling_core.types.doc import ImageRefMode
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.warning("Docling 未安装，请运行: pip install docling")


@dataclass
class DocChunk:
    """文档分块数据结构"""
    content: str                           # 内容
    title: str = ""                        # 标题
    level: int = 0                         # 标题级别
    chunk_type: str = "text"               # 类型: text, table, image, code
    section_path: str = ""                 # 章节路径
    page: int = 0                          # 页码（PDF）
    source_file: str = ""                  # 源文件名
    bbox: Optional[List[float]] = None     # 边界框
    metadata: Dict[str, Any] = field(default_factory=dict)


class DoclingParser:
    """
    Docling 文档解析器

    支持格式：
    - Word (.docx)
    - Excel (.xlsx)
    - PDF
    - HTML
    - TXT
    """

    def __init__(self, use_ocr: bool = False):
        """
        初始化解析器

        Args:
            use_ocr: 是否启用 OCR（用于图片 PDF）
        """
        if not DOCLING_AVAILABLE:
            raise ImportError("Docling 未安装，请运行: pip install docling")

        self.converter = None
        self.use_ocr = use_ocr
        self._init_converter()

    def _init_converter(self):
        """初始化转换器"""
        # PDF 管道选项
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = self.use_ocr
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.do_cell_matching = True

        # 创建转换器
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

    def parse(self, filepath: str) -> Dict[str, Any]:
        """
        解析文档

        Args:
            filepath: 文档路径

        Returns:
            {
                "markdown": "Markdown 格式内容",
                "chunks": [DocChunk, ...],
                "tables": ["表格1", ...],
                "images": ["图片描述", ...],
                "metadata": {...}
            }
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"文件不存在: {filepath}")

        # 执行转换
        result = self.converter.convert(str(filepath))
        doc = result.document

        # 导出为 Markdown
        markdown = doc.export_to_markdown()

        # 提取结构化分块
        chunks = self._extract_chunks(doc, filepath.name)

        # 提取表格
        tables = self._extract_tables(doc)

        # 提取图片描述
        images = self._extract_images(doc)

        return {
            "markdown": markdown,
            "chunks": chunks,
            "tables": tables,
            "images": images,
            "metadata": {
                "source_file": filepath.name,
                "num_pages": getattr(doc, 'num_pages', 0),
                "format": filepath.suffix.lower()
            }
        }

    def _extract_chunks(self, doc, source_file: str) -> List[DocChunk]:
        """从文档中提取结构化分块"""
        chunks = []
        current_section = []
        section_path = []

        # 遍历文档元素
        for item, level in doc.iterate_items():
            # item 是文档元素，level 是层级

            # 获取文本内容
            text = getattr(item, 'text', '') or ''

            # 判断元素类型
            if hasattr(item, 'label'):
                label = item.label.value if hasattr(item.label, 'value') else str(item.label)

                # 标题处理
                if label in ('section_header', 'title', 'heading'):
                    heading_level = getattr(item, 'level', 1) or 1
                    title = text.strip()

                    # 保存之前的段落
                    if current_section:
                        chunk_text = '\n'.join(current_section)
                        if chunk_text.strip():
                            chunks.append(DocChunk(
                                content=chunk_text,
                                title=section_path[-1] if section_path else "",
                                level=heading_level,
                                chunk_type="text",
                                section_path=' > '.join(section_path),
                                source_file=source_file
                            ))
                        current_section = []

                    # 更新章节路径
                    if heading_level <= len(section_path):
                        section_path = section_path[:heading_level-1]
                    section_path.append(title)

                # 段落处理
                elif label in ('paragraph', 'text', 'list_item'):
                    if text.strip():
                        current_section.append(text.strip())

                # 表格处理
                elif label == 'table':
                    # 保存之前的段落
                    if current_section:
                        chunk_text = '\n'.join(current_section)
                        if chunk_text.strip():
                            chunks.append(DocChunk(
                                content=chunk_text,
                                title=section_path[-1] if section_path else "",
                                level=0,
                                chunk_type="text",
                                section_path=' > '.join(section_path),
                                source_file=source_file
                            ))
                        current_section = []

                    # 表格作为独立分块
                    table_text = self._format_table(item)
                    if table_text.strip():
                        chunks.append(DocChunk(
                            content=table_text,
                            title="表格",
                            level=0,
                            chunk_type="table",
                            section_path=' > '.join(section_path),
                            source_file=source_file
                        ))

                # 代码块处理
                elif label in ('code', 'code_block'):
                    if text.strip():
                        current_section.append(f"```\n{text.strip()}\n```")

        # 保存最后的段落
        if current_section:
            chunk_text = '\n'.join(current_section)
            if chunk_text.strip():
                chunks.append(DocChunk(
                    content=chunk_text,
                    title=section_path[-1] if section_path else "",
                    level=0,
                    chunk_type="text",
                    section_path=' > '.join(section_path),
                    source_file=source_file
                ))

        return chunks

    def _format_table(self, table_item) -> str:
        """格式化表格为 Markdown"""
        rows = []

        # 尝试获取表格数据
        if hasattr(table_item, 'data') and table_item.data:
            data = table_item.data
            if hasattr(data, 'grid'):
                for row in data.grid:
                    cells = []
                    for cell in row:
                        cell_text = getattr(cell, 'text', '') or str(cell)
                        cells.append(cell_text.strip())
                    rows.append('| ' + ' | '.join(cells) + ' |')

                # 添加表头分隔符
                if len(rows) > 0:
                    header_row = rows[0]
                    num_cols = header_row.count('|') - 1
                    rows.insert(1, '|' + '|'.join(['---'] * num_cols) + '|')

        # 如果上面方法失败，尝试直接获取文本
        if not rows:
            text = getattr(table_item, 'text', '') or ''
            if text.strip():
                rows.append(text.strip())

        return '\n'.join(rows)

    def _extract_tables(self, doc) -> List[str]:
        """提取所有表格"""
        tables = []
        for item, level in doc.iterate_items():
            if hasattr(item, 'label'):
                label = item.label.value if hasattr(item.label, 'value') else str(item.label)
                if label == 'table':
                    table_text = self._format_table(item)
                    if table_text.strip():
                        tables.append(table_text)
        return tables

    def _extract_images(self, doc) -> List[str]:
        """提取图片描述"""
        images = []
        for item, level in doc.iterate_items():
            if hasattr(item, 'label'):
                label = item.label.value if hasattr(item.label, 'value') else str(item.label)
                if label in ('image', 'figure'):
                    # 获取图片说明
                    caption = getattr(item, 'caption', '') or ''
                    if caption:
                        images.append(caption)
        return images


def parse_docx_with_docling(filepath: str) -> Dict[str, Any]:
    """
    使用 Docling 解析 Word 文档

    Args:
        filepath: Word 文件路径

    Returns:
        解析结果
    """
    parser = DoclingParser()
    return parser.parse(filepath)


def parse_xlsx_with_docling(filepath: str) -> Dict[str, Any]:
    """
    使用 Docling 解析 Excel 文档

    Args:
        filepath: Excel 文件路径

    Returns:
        解析结果
    """
    parser = DoclingParser()
    return parser.parse(filepath)


def parse_file_with_docling(
    filepath: str,
    use_ocr: bool = False
) -> Dict[str, Any]:
    """
    使用 Docling 解析任意支持的文档格式

    Args:
        filepath: 文件路径
        use_ocr: 是否启用 OCR

    Returns:
        解析结果
    """
    parser = DoclingParser(use_ocr=use_ocr)
    return parser.parse(filepath)


def get_chunks_for_rag(
    filepath: str,
    min_chunk_size: int = 50
) -> Tuple[List[str], List[Dict]]:
    """
    获取适合 RAG 系统的分块

    Args:
        filepath: 文件路径
        min_chunk_size: 最小分块大小

    Returns:
        (documents, metadatas) - 文档列表和元数据列表
    """
    result = parse_file_with_docling(filepath)

    documents = []
    metadatas = []

    for chunk in result['chunks']:
        if len(chunk.content.strip()) >= min_chunk_size:
            documents.append(chunk.content)
            metadatas.append({
                'title': chunk.title,
                'level': chunk.level,
                'chunk_type': chunk.chunk_type,
                'section_path': chunk.section_path,
                'source_file': chunk.source_file
            })

    return documents, metadatas


if __name__ == "__main__":
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("用法: python doc_parser_docling.py <文件路径>")
        sys.exit(1)

    filepath = sys.argv[1]

    if not DOCLING_AVAILABLE:
        print("错误: Docling 未安装")
        print("请运行: pip install docling")
        sys.exit(1)

    print(f"正在解析: {filepath}")
    result = parse_file_with_docling(filepath)

    print(f"\n解析完成:")
    print(f"- Markdown 长度: {len(result['markdown'])} 字符")
    print(f"- 分块数量: {len(result['chunks'])}")
    print(f"- 表格数量: {len(result['tables'])}")

    print("\n分块预览:")
    for i, chunk in enumerate(result['chunks'][:5]):
        print(f"\n--- 块 {i+1}: {chunk.title} ({chunk.chunk_type}) ---")
        print(f"路径: {chunk.section_path}")
        print(f"内容长度: {len(chunk.content)} 字符")
        preview = chunk.content[:150] + "..." if len(chunk.content) > 150 else chunk.content
        print(preview)
