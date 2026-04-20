# -*- coding: utf-8 -*-
"""
修复向量库中的图片路径格式

问题：历史数据中 image_path 存储为 "images/xxx.jpg" 格式
修复：统一改为只存储文件名 "xxx.jpg"

使用方式：
    python scripts/fix_image_paths.py [--dry-run]
"""

import argparse
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb


def fix_image_paths(dry_run: bool = False):
    """
    修复向量库中的图片路径格式

    Args:
        dry_run: 仅预览，不实际修改
    """
    chroma_path = "knowledge/vector_store/chroma"
    client = chromadb.PersistentClient(path=chroma_path)

    # 获取所有集合
    collections = client.list_collections()
    print(f"找到 {len(collections)} 个集合")

    for collection in collections:
        print(f"\n处理集合: {collection.name}")

        # 获取所有图片类型的切片
        try:
            results = collection.get(
                where={"chunk_type": "image"},
                include=["metadatas", "documents", "embeddings"]
            )

            if not results["ids"]:
                print(f"  无图片类型切片")
                continue

            print(f"  找到 {len(results['ids'])} 个图片切片")

            # 检查需要修复的路径
            needs_fix = []
            for i, (id, meta) in enumerate(zip(results["ids"], results["metadatas"])):
                image_path = meta.get("image_path", "")
                if image_path and ("/" in image_path or "\\" in image_path):
                    # 路径包含目录，需要修复
                    new_path = os.path.basename(image_path)
                    needs_fix.append({
                        "id": id,
                        "old_path": image_path,
                        "new_path": new_path,
                        "index": i
                    })

            if not needs_fix:
                print(f"  所有路径格式正确，无需修复")
                continue

            print(f"  需要修复 {len(needs_fix)} 条记录:")
            for item in needs_fix[:5]:  # 只显示前5条
                print(f"    {item['old_path']} -> {item['new_path']}")
            if len(needs_fix) > 5:
                print(f"    ... 还有 {len(needs_fix) - 5} 条")

            if dry_run:
                print(f"  [DRY-RUN] 跳过实际修改")
                continue

            # 执行修复
            ids_to_update = []
            metadatas_to_update = []

            for item in needs_fix:
                # 更新元数据
                new_meta = results["metadatas"][item["index"]].copy()
                new_meta["image_path"] = item["new_path"]
                ids_to_update.append(item["id"])
                metadatas_to_update.append(new_meta)

            # 批量更新
            collection.update(
                ids=ids_to_update,
                metadatas=metadatas_to_update
            )
            print(f"  ✓ 已修复 {len(ids_to_update)} 条记录")

        except Exception as e:
            print(f"  处理集合 {collection.name} 时出错: {e}")


def main():
    parser = argparse.ArgumentParser(description="修复向量库中的图片路径格式")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际修改")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY-RUN 模式：仅预览，不修改数据 ===\n")

    fix_image_paths(dry_run=args.dry_run)

    print("\n完成!")


if __name__ == "__main__":
    main()
