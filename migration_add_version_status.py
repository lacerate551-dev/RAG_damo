"""
数据迁移脚本 - 为现有chunks添加版本状态字段

运行此脚本为现有向量库数据添加status、version等字段
"""

import sys
import os

# Windows 编码设置
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from datetime import datetime


def migrate_chunks():
    """为现有chunks添加status字段"""
    from knowledge_base_manager import get_kb_manager

    kb_manager = get_kb_manager()
    collections = kb_manager.list_collections()

    print("=" * 60)
    print("开始迁移 - 为chunks添加版本状态字段")
    print("=" * 60)

    total_migrated = 0

    for coll_info in collections:
        coll_name = coll_info.name
        print(f"\n处理向量库: {coll_name}")

        collection = kb_manager.get_collection(coll_name)
        if not collection:
            continue

        result = collection.get()
        ids = result['ids']
        metadatas = result['metadatas']

        if not ids:
            print(f"  向量库为空，跳过")
            continue

        migrated = 0
        updated_metadatas = []

        for i, (chunk_id, meta) in enumerate(zip(ids, metadatas)):
            # 检查是否已有status字段
            if 'status' not in meta:
                # 添加默认字段
                updated_meta = {
                    **meta,
                    'status': 'active',
                    'version': 'v1',
                    'effective_date': datetime.now().strftime('%Y-%m-%d')
                }
                updated_metadatas.append(updated_meta)
                migrated += 1
            else:
                updated_metadatas.append(meta)

        # 批量更新
        if migrated > 0:
            collection.update(
                ids=ids,
                metadatas=updated_metadatas
            )
            print(f"  迁移了 {migrated} 个chunks")
            total_migrated += migrated
        else:
            print(f"  所有chunks已有status字段，无需迁移")

    print("\n" + "=" * 60)
    print(f"迁移完成！总计迁移 {total_migrated} 个chunks")
    print("=" * 60)


def init_version_tables():
    """初始化版本管理数据库表"""
    import sqlite3

    db_path = "./data/exam_analysis.db"

    print("\n初始化版本管理表...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 文档版本表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            collection TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'v1',
            status TEXT NOT NULL DEFAULT 'active',
            effective_date DATE,
            expiry_date DATE,
            deprecated_date DATETIME,
            deprecated_reason TEXT,
            deprecated_by TEXT,
            change_summary TEXT,
            supersedes TEXT,
            chunk_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            UNIQUE(document_id, collection, version)
        )
    ''')

    # 版本变更日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS version_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            collection TEXT NOT NULL,
            old_version TEXT,
            new_version TEXT,
            old_status TEXT,
            new_status TEXT,
            change_type TEXT NOT NULL,
            reason TEXT,
            changed_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

    print("版本管理表初始化完成")


if __name__ == "__main__":
    print("向量知识库版本管理数据迁移")
    print()

    # 1. 初始化数据库表
    init_version_tables()

    # 2. 迁移chunks元数据
    migrate_chunks()

    print("\n迁移脚本执行完毕！")
