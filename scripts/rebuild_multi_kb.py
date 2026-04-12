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
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

from rag_demo import (
    load_documents,
    smart_split_text,    # 智能分块（语义分块优先）
    EMBEDDING_MODEL_PATH,
    CHROMA_DB_PATH
)
from knowledge_base_manager import KnowledgeBaseManager


# 部门关键词映射
DEPT_KEYWORDS = {
    'finance': ['财务', '报销', '发票', '预算', '支出', '收入', '成本',
                '账目', '会计', '审计', '税务', '薪酬', '财务报表'],
    'hr': ['人事', '招聘', '入职', '离职', '考勤', '请假', '休假',
           '员工', '培训', '绩效', '人员名册', '薪酬制度'],
    'tech': ['技术', '开发', '代码', '系统', '服务器', '数据库', 'API',
             '接口', '部署', '测试', '信息安全', '核心技术'],
    'admin': ['行政', '办公室', '会议室', '采购', '固定资产', '印章',
              '档案', '董事会', '并购', '股权', '差旅管理', '会议纪要'],
    'operation': ['运营', '推广', '营销', '活动', '用户', '增长',
                  '数据', '分析', '项目管理'],
    'legal': ['法务', '合同', '法律', '诉讼', '合规', '风险', '合同台账'],
    'strategy': ['战略', '规划', '发展', '目标', '愿景', '战略规划'],
}


def get_target_kb(filepath: str, security_level: str) -> str:
    """
    判断文档应归属的向量库

    Args:
        filepath: 文件路径（相对路径）
        security_level: 安全级别

    Returns:
        目标向量库名称
    """
    filepath_lower = filepath.lower().replace('\\', '/')

    # 1. 根据目录路径判断（优先级最高）
    if 'public/' in filepath_lower or filepath_lower.startswith('public'):
        return 'public_kb'

    if 'dept_' in filepath_lower:
        # 提取部门名 (dept_finance/xxx.doc -> dept_finance)
        parts = filepath_lower.split('/')
        for part in parts:
            if part.startswith('dept_'):
                return part

    # 2. 根据文件名判断部门
    filename = os.path.basename(filepath)
    filename_base = os.path.splitext(filename)[0]
    for dept, keywords in DEPT_KEYWORDS.items():
        for kw in keywords:
            if kw in filename_base or kw in filename:
                return f'dept_{dept}'

    # 3. 根据安全级别默认分配
    if 'secret/' in filepath_lower:
        return 'dept_admin'
    elif 'confidential/' in filepath_lower:
        return 'dept_general'
    elif 'internal/' in filepath_lower:
        return 'dept_general'

    return 'dept_general'


def main():
    print("=" * 60)
    print("重建多向量知识库")
    print("=" * 60)

    # 1. 加载向量模型
    print("\n[1/6] 加载向量模型...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_PATH)
    print("  ✓ 向量模型加载完成")

    # 2. 初始化知识库管理器
    print("\n[2/6] 初始化知识库管理器...")
    kb_manager = KnowledgeBaseManager(CHROMA_DB_PATH)
    print("  ✓ 知识库管理器初始化完成")

    # 3. 创建向量库
    print("\n[3/6] 创建向量库...")
    collections_to_create = [
        ('public_kb', '公开知识库', '全公司公开文档'),
        ('dept_finance', '财务部知识库', '财务部专属文档'),
        ('dept_hr', '人事部知识库', '人事部专属文档'),
        ('dept_tech', '技术部知识库', '技术部专属文档'),
        ('dept_admin', '行政部知识库', '行政部专属文档'),
        ('dept_operation', '运营部知识库', '运营部专属文档'),
        ('dept_legal', '法务部知识库', '法务部专属文档'),
        ('dept_strategy', '战略部知识库', '战略部专属文档'),
        ('dept_general', '通用知识库', '通用内部文档'),
    ]

    for name, display_name, desc in collections_to_create:
        try:
            kb_manager.create_collection(name, display_name=display_name, description=desc)
            print(f"  ✓ 创建: {name}")
        except Exception as e:
            if 'already exists' in str(e).lower():
                print(f"  - {name} 已存在")
            else:
                print(f"  ! {name} 创建失败: {e}")

    # 4. 加载文档
    print("\n[4/6] 加载文档...")
    documents = load_documents()
    print(f"  共加载 {len(documents)} 个文档")

    # 5. 向量化并写入
    print("\n[5/6] 向量化并写入向量库...")
    stats = {}
    total_chunks = 0

    for doc in documents:
        filename = doc.get('filename', '')
        security_level = doc.get('security_level', 'public')
        target_kb = get_target_kb(filename, security_level)

        chunks_data = []

        # 根据文档类型提取文本块
        if doc.get('type') == 'pdf':
            for page in doc.get('pages', []):
                text = page.get('text', '')
                if text.strip():
                    # 检查是否为 ODL 智能分块（不再二次切分）
                    is_odl_chunk = page.get('is_odl_chunk', False)

                    if is_odl_chunk:
                        # ODL 分块：直接使用，保留结构信息
                        chunks_data.append({
                            'text': text,
                            'metadata': {
                                'source': filename,
                                'page': page.get('page', 0),
                                'page_end': page.get('page_end', page.get('page', 0)),
                                'has_table': page.get('has_table', False),
                                'section': page.get('section', ''),
                                'section_path': page.get('section_path', ''),
                                'level': page.get('level', 0),
                                'is_odl_chunk': True,
                                'security_level': security_level,
                                'collection': target_kb
                            }
                        })
                    else:
                        # 传统分块：智能分块
                        for chunk in smart_split_text(text):
                            chunks_data.append({
                                'text': chunk,
                                'metadata': {
                                    'source': filename,
                                    'page': page.get('page', 0),
                                    'security_level': security_level,
                                    'collection': target_kb
                                }
                            })

        elif doc.get('type') == 'docx':
            for block in doc.get('blocks', []):
                text = block.get('text', '')
                if text.strip():
                    for chunk in smart_split_text(text):
                        chunks_data.append({
                            'text': chunk,
                            'metadata': {
                                'source': filename,
                                'type': block.get('type', 'paragraph'),
                                'is_table': block.get('is_table', False),
                                'security_level': security_level,
                                'collection': target_kb
                            }
                        })

        elif doc.get('type') == 'xlsx':
            for row in doc.get('rows', []):
                text = row.get('text', '')
                if text.strip():
                    chunks_data.append({
                        'text': text,
                        'metadata': {
                            'source': filename,
                            'row': row.get('row', 0),
                            'security_level': security_level,
                            'collection': target_kb
                        }
                    })

        else:
            # txt 或其他
            content = doc.get('content', '')
            if content.strip():
                for chunk in smart_split_text(content):
                    chunks_data.append({
                        'text': chunk,
                        'metadata': {
                            'source': filename,
                            'security_level': security_level,
                            'collection': target_kb
                        }
                    })

        if not chunks_data:
            continue

        texts = [c['text'] for c in chunks_data]
        metadatas = [c['metadata'] for c in chunks_data]

        # 生成向量
        vectors = embedding_model.encode(texts).tolist()

        # 生成 ID
        ids = [f'{filename}_{i}' for i in range(len(texts))]

        # 分批写入向量库（每批 100 个 chunks，避免 HNSW 索引损坏）
        BATCH_SIZE = 100
        try:
            collection = kb_manager.get_collection(target_kb)

            for batch_start in range(0, len(ids), BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, len(ids))
                collection.add(
                    ids=ids[batch_start:batch_end],
                    documents=texts[batch_start:batch_end],
                    embeddings=vectors[batch_start:batch_end],
                    metadatas=metadatas[batch_start:batch_end]
                )

            stats[target_kb] = stats.get(target_kb, 0) + len(texts)
            total_chunks += len(texts)
            print(f"  ✓ {filename[:25]}... -> {target_kb} ({len(texts)} chunks)")
        except Exception as e:
            print(f"  ✗ {filename[:25]}... 写入失败: {e}")

    # 6. 构建 BM25 索引
    print("\n[6/6] 构建 BM25 索引...")
    for coll_name in stats.keys():
        try:
            kb_manager.rebuild_bm25_index(coll_name)
            print(f"  ✓ {coll_name} BM25 索引完成")
        except Exception as e:
            print(f"  ! {coll_name} BM25 索引失败: {e}")

    # 汇总
    print("\n" + "=" * 60)
    print("重建完成")
    print("=" * 60)
    print(f"总文档数: {len(documents)}")
    print(f"总 chunks: {total_chunks}")
    print("\n各向量库统计:")
    for kb, count in sorted(stats.items()):
        print(f"  {kb}: {count} chunks")

    print("\n向量库列表:")
    for coll in kb_manager.list_collections():
        doc_count = kb_manager.get_document_count(coll.name)
        print(f"  {coll.name}: {doc_count} documents")

    # 显式强制回收，触发 ChromaDB 刷盘以防 HNSW 损坏
    import gc
    import time
    print("\n等待底层向量引擎写入 HNSW 索引大文件...")
    time.sleep(15) # 给底层 Rust 后台线程留出足够的时间刷盘
    kb_manager._clients.clear()
    del kb_manager
    gc.collect()
    print("写入完成！")


if __name__ == "__main__":
    main()
