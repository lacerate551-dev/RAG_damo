"""
PDF pdfplumber 解析器

基础 PDF 文本提取，按页返回带结构信息的内容列表。
作为 OpenDataLoader 解析器的回退方案。
"""

import pdfplumber


def extract_text_from_pdf_plumber(filepath):
    """从PDF提取文本，返回带页码和结构信息的内容列表（pdfplumber 实现）"""
    pages_content = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    # 检测是否包含表格
                    tables = page.extract_tables()
                    has_table = len(tables) > 0

                    # 尝试识别章节标题（通常是短行、字号较大、以数字开头等）
                    lines = page_text.split('\n')
                    section_title = ""
                    for line in lines[:5]:  # 只检查前几行
                        line = line.strip()
                        # 章节标题特征：短、以数字或第X章/节开头
                        if len(line) < 30 and (line.startswith(('第', '一、', '二、', '三、', '四、', '五、', '1.', '2.', '3.')) or
                            any(keyword in line for keyword in ['章', '节', '规定', '制度', '办法'])):
                            section_title = line
                            break

                    pages_content.append({
                        'text': page_text,
                        'page': page_num + 1,
                        'has_table': has_table,
                        'section': section_title
                    })
    except Exception as e:
        print(f"      PDF解析错误 {filepath}: {e}")
    return pages_content
