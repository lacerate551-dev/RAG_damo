"""
数据库迁移脚本：为 messages 表添加 metadata 列

运行方式：
    python scripts/migrate_add_metadata.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rag_core.db")

def migrate():
    """添加 metadata 列到 messages 表"""
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查列是否已存在
        cursor.execute("PRAGMA table_info(messages)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'metadata' in columns:
            print("✓ metadata 列已存在，无需迁移")
            return

        # 添加 metadata 列
        print("正在添加 metadata 列...")
        cursor.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        conn.commit()
        print("✓ 迁移完成！")

    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
