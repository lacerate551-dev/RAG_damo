"""
重建多向量知识库脚本

将现有文档按部门/类别分配到不同的向量库中
"""

import os
import sys

# Windows 编码设置
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sentence_transformers import SentenceTransformer

from config import DOCUMENTS_PATH, EMBEDDING_MODEL_PATH
from parsers import (
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_xlsx,
    extract_text_from_txt,
    IMAGE_EXTRACTOR_AVAILABLE,
    get_images_base_path
)
from core.chunker import split_text
from knowledge.manager import KnowledgeBaseManager, PUBLIC_KB_NAME


def get_target_kb(filepath: str) -> str:
    """
    判断文档应归属的向量库

    根据文件所在目录判断：
    - public/ -> public_kb
    - dept_finance/ -> dept_finance
    - dept_hr/ -> dept_hr
    等
    """
    # 标准化路径
    filepath_lower = filepath.replace('\\', '/').lower()

    # 1. 根据目录路径判断（优先级最高）
    if 'public/' in filepath_lower or filepath_lower.startswith('public'):
        return PUBLIC_KB_NAME

    # 检查是否在部门目录下
    for dept in ['finance', 'hr', 'tech', 'admin', 'operation', 'legal', 'strategy', 'marketing']:
        if f'dept_{dept}/' in filepath_lower or filepath_lower.startswith(f'dept_{dept}'):
            return f'dept_{dept}'

    # 默认放入 public
    return PUBLIC_KB_NAME


def scan_documents(documents_path: str) -> list:
    """扫描文档目录"""
    documents = []
    supported_extensions = {'.pdf', '.docx', '.xlsx', '.txt'}

    for root, dirs, files in os.walk(documents_path):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in supported_extensions:
                filepath = os.path.join(root, filename)
                relpath = os.path.relpath(filepath, documents_path)
                documents.append({
                    'filepath': filepath,
                    'relpath': relpath,
                    'filename': filename,
                    'ext': ext
                })

    return documents


def process_document(doc_info: dict, embedding_model, images_output_dir: str = None) -> tuple:
    """
    处理单个文档，返回 (target_kb, chunks, images_count)

    Returns:
        (目标向量库名, [(text, metadata), ...], 提取的图片数量)
    """
    filepath = doc_info['filepath']
    filename = doc_info['filename']
    ext = doc_info['ext']
    relpath = doc_info['relpath']

    # 确定目标向量库
    target_kb = get_target_kb(relpath)

    chunks = []
    images_count = 0

    try:
        if ext == '.pdf':
            # 提取文本和图片
            extract_img = IMAGE_EXTRACTOR_AVAILABLE and images_output_dir is not None
            result = extract_text_from_pdf(
                filepath,
                extract_images=extract_img,
                images_output_dir=images_output_dir
            )

            # 处理返回值（可能是 tuple 或 list）
            if isinstance(result, tuple):
                pages, doc_images = result
                images_count = len(doc_images) if doc_images else 0
            else:
                pages = result
                images_count = 0

            for i, page in enumerate(pages):
                text = page.get('text', '')
                if not text.strip():
                    continue

                # 检查是否已经是智能分块
                if page.get('is_odl_chunk'):
                    # 过滤空的 metadata 字段（ChromaDB 不允许空列表）
                    metadata = {
                        'source': filename,
                        'page': page.get('page', 0),
                        'page_end': page.get('page_end', 0),
                        'has_table': page.get('has_table', False),
                        'section': page.get('section', ''),
                        'section_path': page.get('section_path', ''),
                        'is_odl_chunk': True,
                        'collection': target_kb,
                        'status': 'active'
                    }
                    # 图片信息序列化为 JSON 字符串（ChromaDB metadata 只支持基本类型）
                    if page.get('images'):
                        import json
                        metadata['images_json'] = json.dumps(page.get('images'), ensure_ascii=False)

                    chunks.append((text, metadata))
                else:
                    # 传统分块
                    for j, chunk in enumerate(split_text(text)):
                        chunks.append((chunk, {
                            'source': filename,
                            'page': page.get('page', 0),
                            'chunk_index': j,
                            'has_table': page.get('has_table', False),
                            'section': page.get('section', ''),
                            'collection': target_kb,
                            'status': 'active'
                        }))

        elif ext == '.docx':
            blocks = extract_text_from_docx(filepath)
            for i, block in enumerate(blocks):
                text = block.get('text', '')
                if not text.strip() or len(text.strip()) < 10:
                    continue

                if block.get('is_docling_chunk'):
                    chunks.append((text, {
                        'source': filename,
                        'section': block.get('section', ''),
                        'is_table': block.get('is_table', False),
                        'is_docling_chunk': True,
                        'collection': target_kb,
                        'status': 'active'
                    }))
                else:
                    # 检查是否是表格，表格不分割
                    if block.get('is_table'):
                        chunks.append((text, {
                            'source': filename,
                            'is_table': True,
                            'collection': target_kb,
                            'status': 'active'
                        }))
                    else:
                        for j, chunk in enumerate(split_text(text)):
                            chunks.append((chunk, {
                                'source': filename,
                                'chunk_index': len(chunks),
                                'is_table': False,
                                'collection': target_kb,
                                'status': 'active'
                            }))

        elif ext == '.xlsx':
            rows = extract_text_from_xlsx(filepath)
            for row in rows:
                text = row.get('text', '')
                if not text.strip() or len(text.strip()) < 5:
                    continue
                chunks.append((text, {
                    'source': filename,
                    'sheet': row.get('sheet', ''),
                    'row': row.get('row', 0),
                    'is_header': row.get('is_header', False),
                    'collection': target_kb,
                    'status': 'active'
                }))

        elif ext == '.txt':
            content = extract_text_from_txt(filepath)
            if content.strip():
                for i, chunk in enumerate(split_text(content)):
                    chunks.append((chunk, {
                        'source': filename,
                        'chunk_index': i,
                        'collection': target_kb,
                        'status': 'active'
                    }))

    except Exception as e:
        print(f"    解析错误 {filename}: {e}")

    return target_kb, chunks, images_count


def main():
    print("=" * 60)
    print("重建多向量知识库")
    print("=" * 60)

    # 0. 清理现有向量库（避免重复数据）
    print("\n[0/5] 清理现有向量库...")
    import shutil
    vector_store_path = os.path.join(PROJECT_ROOT, "knowledge", "vector_store")
    if os.path.exists(vector_store_path):
        shutil.rmtree(vector_store_path)
        print("  [OK] 已删除旧向量库")
    else:
        print("  [-] 无旧向量库需要清理")

    # 1. 加载向量模型
    print("\n[1/6] 加载向量模型...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
    print("  [OK] 向量模型加载完成")

    # 2. 初始化知识库管理器
    print("\n[2/6] 初始化知识库管理器...")
    kb_manager = KnowledgeBaseManager()
    print("  [OK] 知识库管理器初始化完成")

    # 3. 创建图片输出目录
    images_output_dir = None
    if IMAGE_EXTRACTOR_AVAILABLE:
        images_output_dir = get_images_base_path()
        os.makedirs(images_output_dir, exist_ok=True)
        print(f"\n[2.5/5] 图片输出目录: {images_output_dir}")

    # 3. 创建向量库
    print("\n[3/6] 创建向量库...")
    collections_to_create = [
        (PUBLIC_KB_NAME, '公开知识库', '全公司公开文档'),
        ('dept_finance', '财务部知识库', '财务部专属文档'),
        ('dept_hr', '人事部知识库', '人事部专属文档'),
        ('dept_tech', '技术部知识库', '技术部专属文档'),
        ('dept_admin', '行政部知识库', '行政部专属文档'),
        ('dept_operation', '运营部知识库', '运营部专属文档'),
        ('dept_legal', '法务部知识库', '法务部专属文档'),
        ('dept_strategy', '战略部知识库', '战略部专属文档'),
        ('dept_marketing', '市场部知识库', '市场部专属文档'),
    ]

    for name, display_name, desc in collections_to_create:
        success, msg = kb_manager.create_collection(name, display_name=display_name, description=desc)
        if success:
            print(f"  [OK] 创建: {name}")
        else:
            print(f"  [-] {name}: {msg}")

    # 4. 扫描文档
    print("\n[4/6] 扫描文档...")
    documents = scan_documents(DOCUMENTS_PATH)
    print(f"  共发现 {len(documents)} 个文档")

    # 5. 向量化并写入
    print("\n[5/6] 向量化并写入向量库...")
    stats = {}
    total_chunks = 0
    total_images = 0
    BATCH_SIZE = 100  # 每批写入数量

    for i, doc in enumerate(documents):
        target_kb, chunks, images_count = process_document(doc, embedding_model, images_output_dir)
        total_images += images_count

        if not chunks:
            continue

        # 生成向量
        texts = [c[0] for c in chunks]
        metadatas = [c[1] for c in chunks]
        vectors = embedding_model.encode(texts).tolist()

        # 生成 ID
        ids = [f'{doc["filename"]}_{j}' for j in range(len(texts))]

        # 分批写入
        try:
            collection = kb_manager.get_collection(target_kb)
            if collection:
                for batch_start in range(0, len(ids), BATCH_SIZE):
                    batch_end = min(batch_start + BATCH_SIZE, len(ids))
                    collection.add(
                        ids=ids[batch_start:batch_end],
                        documents=texts[batch_start:batch_end],
                        embeddings=vectors[batch_start:batch_end],
                        metadatas=metadatas[batch_start:batch_end]
                    )

                stats[target_kb] = stats.get(target_kb, 0) + len(chunks)
                total_chunks += len(chunks)

                if (i + 1) % 10 == 0:
                    print(f"  已处理 {i + 1}/{len(documents)} 文档, 累计 {total_chunks} chunks")
        except Exception as e:
            print(f"  [X] {doc['filename'][:30]}... 写入失败: {e}")

    # 重建 BM25 索引
    print("\n重建 BM25 索引...")
    for kb_name in stats.keys():
        try:
            kb_manager.rebuild_bm25_index(kb_name)
            print(f"  [OK] {kb_name} BM25 索引完成")
        except Exception as e:
            print(f"  [!] {kb_name} BM25 索引失败: {e}")

    # 汇总
    print("\n" + "=" * 60)
    print("重建完成")
    print("=" * 60)
    print(f"总文档数: {len(documents)}")
    print(f"总 chunks: {total_chunks}")
    print(f"提取图片: {total_images} 张")
    print("\n各向量库统计:")
    for kb, count in sorted(stats.items()):
        print(f"  {kb}: {count} chunks")

    # 验证
    print("\n向量库列表:")
    for coll in kb_manager.list_collections():
        doc_count = coll.document_count
        print(f"  {coll.name}: {doc_count} documents")

    # 显式强制回收
    import gc
    import time
    print("\n等待底层向量引擎写入...")
    time.sleep(10)
    kb_manager._clients.clear()
    del kb_manager
    gc.collect()
    print("完成！")


if __name__ == "__main__":
    main()
