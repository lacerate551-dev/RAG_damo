"""
RAG Demo - 基于本地向量模型 + Chroma + Qwen API 的简单知识库问答系统
支持格式: PDF, Word(.docx/.doc), Excel(.xlsx), TXT
"""

import os
from sentence_transformers import SentenceTransformer
import chromadb
from openai import OpenAI
import pdfplumber
from docx import Document
from openpyxl import load_workbook
import docx2txt

# 导入配置
try:
    from config import API_KEY, BASE_URL, MODEL
except ImportError:
    print("错误: 未找到config.py文件")
    print("请复制config.example.py为config.py并填入你的API Key")
    exit(1)

# ========== 配置 ==========
EMBEDDING_MODEL_PATH = "./bge-base-zh-v1.5"
CHROMA_DB_PATH = "./chroma_db"
DOCUMENTS_PATH = "./documents"


# ========== 初始化组件 ==========
print("=" * 50)
print("RAG Demo 知识库问答系统")
print("=" * 50)

print("\n[1/3] 加载本地向量模型...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
print(f"      模型加载完成: {EMBEDDING_MODEL_PATH}")

print("\n[2/3] 初始化向量数据库...")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_or_create_collection(
    name="knowledge_base",
    metadata={"description": "RAG Demo 知识库"}
)
print(f"      数据库路径: {CHROMA_DB_PATH}")

print("\n[3/3] 初始化大模型客户端...")
llm_client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)
print(f"      API地址: {BASE_URL}")
print(f"      模型: {MODEL}")


# ========== 文件管理函数 ==========
def list_indexed_files():
    """列出向量库中已索引的文件"""
    results = collection.get()
    if not results['metadatas']:
        return {}

    # 统计每个文件的片段数
    from collections import Counter
    file_chunks = Counter()
    for meta in results['metadatas']:
        file_chunks[meta['source']] += 1

    return dict(file_chunks)


def delete_file_from_index(filename):
    """从向量库中删除指定文件的所有片段"""
    # 获取该文件的所有ID
    results = collection.get(
        where={"source": filename}
    )

    if not results['ids']:
        print(f"文件未在知识库中: {filename}")
        return 0

    # 删除
    collection.delete(ids=results['ids'])
    deleted_count = len(results['ids'])
    print(f"已删除 {filename} 的 {deleted_count} 个片段")
    return deleted_count


def add_file_to_index(filepath):
    """添加单个文件到向量库"""
    rel_path = os.path.relpath(filepath, DOCUMENTS_PATH)
    ext = os.path.splitext(filepath)[1].lower()

    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx'}
    if ext not in supported_extensions:
        print(f"不支持的文件格式: {ext}")
        return 0

    total_chunks = 0

    # 根据文件类型处理
    if ext == '.pdf':
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
                    chunk_id = f"{rel_path}_p{page_num}_{i}"

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[{
                            'source': rel_path,
                            'page': page_num,
                            'chunk_index': i,
                            'has_table': has_table,
                            'section': section
                        }]
                    )
                    total_chunks += 1
            print(f"添加 {rel_path}: {total_chunks} 个片段 (PDF, {len(pages)}页)")

    elif ext == '.docx':
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
                    chunk_id = f"{rel_path}_{total_chunks}_{i}"

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[{
                            'source': rel_path,
                            'chunk_index': total_chunks,
                            'is_table': is_table,
                            'section': section
                        }]
                    )
                    total_chunks += 1
            tables_count = sum(1 for b in blocks if b.get('is_table'))
            print(f"添加 {rel_path}: {total_chunks} 个片段 (Word, {len(blocks)}段落)")

    elif ext == '.xlsx':
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
                chunk_id = f"{rel_path}_{sheet}_{row_num}"

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[full_text],
                    metadatas=[{
                        'source': rel_path,
                        'sheet': sheet,
                        'row': row_num,
                        'is_header': is_header
                    }]
                )
                total_chunks += 1
            sheets = set(r['sheet'] for r in rows)
            print(f"添加 {rel_path}: {total_chunks} 个片段 (Excel, {len(sheets)}工作表)")

    elif ext == '.txt':
        content = extract_text_from_txt(filepath)
        if content.strip():
            chunks = split_text(content)
            for i, chunk in enumerate(chunks):
                vector = embedding_model.encode(chunk).tolist()
                chunk_id = f"{rel_path}_{i}"

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[chunk],
                    metadatas=[{
                        'source': rel_path,
                        'chunk_index': i
                    }]
                )
                total_chunks += 1
            print(f"添加 {rel_path}: {total_chunks} 个片段 (TXT)")

    return total_chunks


def sync_documents():
    """同步文档目录与向量库（增量更新）"""
    print("\n" + "=" * 50)
    print("同步文档")
    print("=" * 50)

    # 获取向量库中已有的文件
    indexed_files = set(list_indexed_files().keys())
    print(f"\n向量库中已有 {len(indexed_files)} 个文件")

    # 扫描文档目录
    current_files = set()
    supported_extensions = {'.txt', '.pdf', '.docx', '.xlsx'}

    for root, dirs, files in os.walk(DOCUMENTS_PATH):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in supported_extensions:
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, DOCUMENTS_PATH)
                current_files.add(rel_path)

    print(f"文档目录中有 {len(current_files)} 个文件")

    # 需要新增的文件
    files_to_add = current_files - indexed_files
    # 需要删除的文件
    files_to_delete = indexed_files - current_files

    if not files_to_add and not files_to_delete:
        print("\n文档已是最新，无需同步")
        return

    # 删除不存在的文件
    if files_to_delete:
        print(f"\n需要删除 {len(files_to_delete)} 个文件:")
        for f in sorted(files_to_delete):
            print(f"  - {f}")
            delete_file_from_index(f)

    # 添加新文件
    if files_to_add:
        print(f"\n需要添加 {len(files_to_add)} 个新文件:")
        for f in sorted(files_to_add):
            print(f"  + {f}")
            filepath = os.path.join(DOCUMENTS_PATH, f)
            add_file_to_index(filepath)

    print(f"\n同步完成，当前共 {collection.count()} 个片段")


# ========== 文档处理函数 ==========
def extract_text_from_pdf(filepath):
    """从PDF提取文本，返回带页码和结构信息的内容列表"""
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


def extract_text_from_docx(filepath):
    """从Word文档提取文本，返回带结构信息的内容块列表"""
    content_blocks = []

    # 首先尝试用docx2txt提取（兼容性更好）
    try:
        full_text = docx2txt.process(filepath)
        if full_text and full_text.strip():
            # 按段落分割
            for para in full_text.split('\n\n'):
                text = para.strip()
                if text:
                    content_blocks.append({
                        'text': text,
                        'is_heading': False,
                        'section': text[:30] if len(text) < 30 else text[:30] + '...',
                        'is_table': False
                    })
            return content_blocks
    except Exception as e:
        print(f"      docx2txt解析失败，尝试python-docx: {e}")

    # 备用：尝试python-docx
    try:
        doc = Document(filepath)

        current_section = ""
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # 检测是否为标题（通过样式或格式）
            is_heading = False
            if para.style.name.startswith('Heading') or para.style.name.startswith('标题'):
                is_heading = True
                current_section = text
            # 其他标题特征：短、以特定格式开头
            elif len(text) < 50 and (text.startswith(('第', '一、', '二、', '三、', '四、', '五、')) or
                                      text.endswith(('章', '节', '规定', '制度', '办法', '表'))):
                is_heading = True
                current_section = text

            content_blocks.append({
                'text': text,
                'is_heading': is_heading,
                'section': current_section if current_section else text[:20],
                'is_table': False
            })

        # 提取表格内容
        for table_idx, table in enumerate(doc.tables):
            table_text = []
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                if row_text.strip(" |"):
                    table_text.append(row_text)
            if table_text:
                content_blocks.append({
                    'text': "【表格内容】\n" + "\n".join(table_text),
                    'is_heading': False,
                    'section': current_section,
                    'is_table': True
                })
    except Exception as e:
        print(f"      Word解析错误 {filepath}: {e}")
    return content_blocks


def extract_text_from_xlsx(filepath):
    """从Excel提取文本，返回带行列信息的内容块列表"""
    content_blocks = []
    try:
        wb = load_workbook(filepath, data_only=True)
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]

            # 获取表头（第一行）
            header_row = None
            first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if first_row:
                header_row = " | ".join(str(cell) if cell is not None else "" for cell in first_row)

            # 遍历所有行，记录行号
            for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
                if row_text.strip(" |"):
                    is_header = (row_idx == 1)
                    content_blocks.append({
                        'text': row_text,
                        'sheet': sheet_name,
                        'row': row_idx,
                        'is_header': is_header,
                        'header': header_row if not is_header else None
                    })
    except Exception as e:
        print(f"      Excel解析错误 {filepath}: {e}")
    return content_blocks


def extract_text_from_txt(filepath):
    """从TXT提取文本"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # 尝试其他编码
        try:
            with open(filepath, 'r', encoding='gbk') as f:
                return f.read()
        except Exception as e:
            print(f"      TXT解析错误 {filepath}: {e}")
            return ""
    except Exception as e:
        print(f"      TXT解析错误 {filepath}: {e}")
        return ""


def load_documents():
    """递归加载文档目录下的所有支持的文件"""
    documents = []
    supported_extensions = {'.txt', '.pdf', '.docx', '.doc', '.xlsx'}

    if not os.path.exists(DOCUMENTS_PATH):
        print(f"错误: 文档目录不存在 - {DOCUMENTS_PATH}")
        return documents

    # 递归遍历目录
    for root, dirs, files in os.walk(DOCUMENTS_PATH):
        for filename in files:
            filepath = os.path.join(root, filename)
            ext = os.path.splitext(filename)[1].lower()

            if ext not in supported_extensions:
                continue

            # 计算相对路径（用于显示）
            rel_path = os.path.relpath(filepath, DOCUMENTS_PATH)

            # 根据文件类型提取文本
            if ext == '.pdf':
                # PDF特殊处理，返回带页码的列表
                pages = extract_text_from_pdf(filepath)
                if pages:
                    documents.append({
                        'filename': rel_path,
                        'type': 'pdf',
                        'pages': pages
                    })
                    print(f"      加载文档: {rel_path} (PDF, {len(pages)}页)")
            elif ext in {'.docx', '.doc'}:
                # Word返回带结构的内容块列表
                blocks = extract_text_from_docx(filepath)
                if blocks:
                    documents.append({
                        'filename': rel_path,
                        'type': 'docx',
                        'blocks': blocks
                    })
                    tables_count = sum(1 for b in blocks if b.get('is_table'))
                    print(f"      加载文档: {rel_path} (Word, {len(blocks)}段落, {tables_count}表格)")
            elif ext == '.xlsx':
                # Excel返回带行列信息的内容块列表
                rows = extract_text_from_xlsx(filepath)
                if rows:
                    documents.append({
                        'filename': rel_path,
                        'type': 'xlsx',
                        'rows': rows
                    })
                    sheets = set(r['sheet'] for r in rows)
                    print(f"      加载文档: {rel_path} (Excel, {len(sheets)}工作表, {len(rows)}行)")
            elif ext == '.txt':
                content = extract_text_from_txt(filepath)
                if content.strip():
                    documents.append({
                        'filename': rel_path,
                        'content': content,
                        'type': 'txt'
                    })
                    print(f"      加载文档: {rel_path} (TXT)")

    return documents


def split_text(text, chunk_size=300, overlap=50):
    """将文本切分成重叠片段"""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # 尝试在句子边界处切分
        if end < len(text):
            # 查找最后一个句号、问号或感叹号
            last_period = max(
                chunk.rfind('。'),
                chunk.rfind('？'),
                chunk.rfind('！'),
                chunk.rfind('\n')
            )
            if last_period > chunk_size // 2:
                chunk = chunk[:last_period + 1]
                end = start + last_period + 1

        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap

    return chunks


def build_knowledge_base(force=False):
    """构建知识库"""
    print("\n" + "=" * 50)
    print("构建知识库")
    print("=" * 50)

    # 检查是否已有数据
    existing_count = collection.count()
    if existing_count > 0:
        print(f"\n知识库已有 {existing_count} 条记录")
        if not force:
            print("保持现有知识库 (使用 --rebuild 参数强制重建)")
            return
        # 清空现有数据
        ids = collection.get()['ids']
        if ids:
            collection.delete(ids=ids)
            print("已清空原有数据")

    # 加载文档
    print("\n加载文档...")
    documents = load_documents()

    if not documents:
        print("未找到任何文档")
        return

    # 切分并向量化
    print("\n处理文档...")
    total_chunks = 0

    for doc in documents:
        # PDF特殊处理，按页切分
        if doc['type'] == 'pdf':
            doc_chunks = 0
            for page_info in doc['pages']:
                page_text = page_info['text']
                page_num = page_info['page']
                has_table = page_info.get('has_table', False)
                section = page_info.get('section', '')

                chunks = split_text(page_text)
                doc_chunks += len(chunks)

                for i, chunk in enumerate(chunks):
                    vector = embedding_model.encode(chunk).tolist()
                    chunk_id = f"{doc['filename']}_p{page_num}_{i}"

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[{
                            'source': doc['filename'],
                            'page': page_num,
                            'chunk_index': i,
                            'has_table': has_table,
                            'section': section
                        }]
                    )
                    total_chunks += 1
            print(f"  {doc['filename']}: {doc_chunks} 个片段")

        # Word文档处理，按内容块处理
        elif doc['type'] == 'docx':
            doc_chunks = 0
            for block in doc['blocks']:
                text = block['text']
                if len(text.strip()) < 10:  # 跳过太短的内容
                    continue

                is_table = block.get('is_table', False)
                section = block.get('section', '')

                # 表格内容整体保留，不切分
                if is_table:
                    chunks = [text]
                else:
                    chunks = split_text(text)

                doc_chunks += len(chunks)

                for i, chunk in enumerate(chunks):
                    vector = embedding_model.encode(chunk).tolist()
                    chunk_id = f"{doc['filename']}_{doc_chunks}_{i}"

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[{
                            'source': doc['filename'],
                            'chunk_index': doc_chunks,
                            'is_table': is_table,
                            'section': section
                        }]
                    )
                    total_chunks += 1
            print(f"  {doc['filename']}: {doc_chunks} 个片段")

        # Excel处理，按行处理
        elif doc['type'] == 'xlsx':
            doc_chunks = 0
            for row_info in doc['rows']:
                text = row_info['text']
                if len(text.strip()) < 5:  # 跳过空行
                    continue

                sheet = row_info['sheet']
                row_num = row_info['row']
                is_header = row_info.get('is_header', False)
                header = row_info.get('header', '')

                # 如果不是表头行，添加表头信息作为上下文
                full_text = text
                if header and not is_header:
                    full_text = f"【表头: {header}】\n{text}"

                chunks = [full_text]  # 每行作为一个单元
                doc_chunks += len(chunks)

                for i, chunk in enumerate(chunks):
                    vector = embedding_model.encode(chunk).tolist()
                    chunk_id = f"{doc['filename']}_{sheet}_{row_num}"

                    collection.add(
                        ids=[chunk_id],
                        embeddings=[vector],
                        documents=[chunk],
                        metadatas=[{
                            'source': doc['filename'],
                            'sheet': sheet,
                            'row': row_num,
                            'is_header': is_header
                        }]
                    )
                    total_chunks += 1
            print(f"  {doc['filename']}: {doc_chunks} 个片段")

        # 其他文档类型处理（TXT等）
        else:
            chunks = split_text(doc['content'])
            print(f"  {doc['filename']}: {len(chunks)} 个片段")

            for i, chunk in enumerate(chunks):
                vector = embedding_model.encode(chunk).tolist()
                chunk_id = f"{doc['filename']}_{i}"

                collection.add(
                    ids=[chunk_id],
                    embeddings=[vector],
                    documents=[chunk],
                    metadatas=[{
                        'source': doc['filename'],
                        'chunk_index': i
                    }]
                )
                total_chunks += 1

    print(f"\n知识库构建完成，共 {total_chunks} 个片段")


# ========== 检索函数 ==========
def search_knowledge(query, top_k=3):
    """检索相关知识片段"""
    # 问题转向量
    query_vector = embedding_model.encode(query).tolist()

    # 向量检索
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k
    )

    return results


def generate_answer(query, context):
    """调用大模型生成回答"""
    prompt = f"""你是一个智能助手，请根据以下参考资料回答用户的问题。
如果参考资料中没有相关信息，请直接说明"参考资料中没有相关信息"。

回答时请注意：
1. 说明信息来源（文件名、页码/行号等）
2. 如果是表格数据，请用结构化的方式呈现
3. 引用具体条款时标注章节名称

参考资料：
{context}

用户问题：{query}

回答："""

    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"调用大模型失败: {str(e)}"


def chat(query=None):
    """交互式问答或单次问答"""
    if query:
        # 单次问答模式
        return process_query(query)

    # 交互模式
    print("\n" + "=" * 50)
    print("知识库问答")
    print("=" * 50)
    print("命令 (以 / 开头):")
    print("  /quit    - 退出程序")
    print("  /rebuild - 完全重建知识库")
    print("  /sync    - 同步文档（增量更新）")
    print("  /add <文件名> - 添加单个文件")
    print("  /del <文件名> - 删除单个文件")
    print("  /list    - 列出已索引的文件")
    print("  /help    - 显示帮助信息")
    print("其他输入将作为问题进行问答")
    print("=" * 50)

    while True:
        print("\n" + "-" * 30)
        query = input("\n请输入问题或命令: ").strip()

        if not query:
            continue

        # 解析命令（以 / 开头）
        if query.startswith('/'):
            cmd = query.lower()

            if cmd == '/quit':
                print("\n感谢使用，再见!")
                break

            if cmd == '/rebuild':
                build_knowledge_base(force=True)
                continue

            if cmd == '/sync':
                sync_documents()
                continue

            if cmd == '/list':
                files = list_indexed_files()
                print(f"\n已索引文件 ({len(files)} 个):")
                for f, count in sorted(files.items()):
                    print(f"  {f}: {count} 片段")
                continue

            if cmd == '/help':
                print("\n命令列表:")
                print("  /quit    - 退出程序")
                print("  /rebuild - 完全重建知识库")
                print("  /sync    - 同步文档（增量更新）")
                print("  /add <文件名> - 添加单个文件")
                print("  /del <文件名> - 删除单个文件")
                print("  /list    - 列出已索引的文件")
                print("  /help    - 显示帮助信息")
                continue

            if cmd.startswith('/add '):
                filename = query[5:].strip()
                filepath = os.path.join(DOCUMENTS_PATH, filename)
                if os.path.exists(filepath):
                    add_file_to_index(filepath)
                else:
                    print(f"文件不存在: {filename}")
                continue

            if cmd.startswith('/del '):
                filename = query[5:].strip()
                delete_file_from_index(filename)
                continue

            # 未知命令
            print(f"未知命令: {query}")
            print("输入 /help 查看可用命令")
            continue

        # 不是命令，作为问题处理
        process_query(query)


def process_query(query):
    """处理单个查询"""
    # 检索相关内容
    print("\n[检索中...]")
    results = search_knowledge(query)

    if not results['documents'][0]:
        print("未找到相关内容")
        return "未找到相关内容"

    # 组装上下文
    context_parts = []
    sources = set()

    for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
        # 构建来源信息字符串
        source_parts = [meta['source']]

        if 'page' in meta:
            source_parts.append(f"第{meta['page']}页")
        if 'sheet' in meta and 'row' in meta:
            source_parts.append(f"工作表\"{meta['sheet']}\"第{meta['row']}行")
        if 'section' in meta and meta['section']:
            source_parts.append(f"【{meta['section']}】")
        if meta.get('is_table'):
            source_parts.append("(表格)")
        if meta.get('is_header'):
            source_parts.append("(表头)")

        source_str = " ".join(source_parts)
        context_parts.append(f"【来源: {source_str}】\n{doc}")
        sources.add(meta['source'])

    context = "\n\n".join(context_parts)

    print(f"找到 {len(results['documents'][0])} 个相关片段")
    print(f"涉及文档: {', '.join(sources)}")

    # 生成回答
    print("\n[生成回答中...]")
    answer = generate_answer(query, context)

    print("\n" + "=" * 50)
    print("回答:")
    print("-" * 30)
    print(answer)
    print("-" * 30)

    # 显示检索到的片段
    print("\n参考片段:")
    for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0]), 1):
        preview = doc[:100] + "..." if len(doc) > 100 else doc

        # 构建来源信息
        source_info = meta['source']
        if 'page' in meta:
            source_info += f" 第{meta['page']}页"
        if 'sheet' in meta and 'row' in meta:
            source_info += f" [{meta['sheet']} 第{meta['row']}行]"
        if 'section' in meta and meta['section']:
            source_info += f" 【{meta['section']}】"
        if meta.get('is_table'):
            source_info += " [表格]"
        if meta.get('is_header'):
            source_info += " [表头]"

        print(f"  [{i}] {source_info}: {preview}")

    return answer


# ========== 主程序 ==========
if __name__ == "__main__":
    import sys

    # 解析命令行参数
    args = sys.argv[1:]
    force_rebuild = "--rebuild" in args
    sync_mode = "--sync" in args
    list_mode = "--list" in args

    if force_rebuild:
        args.remove("--rebuild")
    if sync_mode:
        args.remove("--sync")
    if list_mode:
        args.remove("--list")

    # 命令行模式
    if list_mode:
        # 列出文件
        files = list_indexed_files()
        print(f"已索引文件 ({len(files)} 个):")
        for f, count in sorted(files.items()):
            print(f"  {f}: {count} 片段")

    elif sync_mode:
        # 同步文档
        sync_documents()

    elif force_rebuild:
        # 强制重建
        build_knowledge_base(force=True)
        print(f"\n知识库统计:")
        print(f"  总片段数: {collection.count()}")

    elif args:
        # 单次问答模式
        build_knowledge_base(force=False)
        query = " ".join(args)
        print(f"\n问题: {query}")
        process_query(query)

    else:
        # 交互模式
        print(f"\n当前知识库: {collection.count()} 个片段")
        chat()