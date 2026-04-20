# -*- coding: utf-8 -*-
"""
分析 MinerU content_list.json，找出图片数量不一致的原因
"""
import json
import os
from collections import Counter
from pathlib import Path

# 找到 content_list.json
base = Path(r".data/mineru_output/a2569e0bfa76/三峡公报_1-15页/auto")
cl_path = base / "三峡公报_1-15页_content_list.json"
cl_v2_path = base / "三峡公报_1-15页_content_list_v2.json"

for path, label in [(cl_path, "content_list.json"), (cl_v2_path, "content_list_v2.json")]:
    if not path.exists():
        print(f"{label} 不存在")
        continue

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n{'='*60}")
    print(f"文件: {label}, 共 {len(data)} 条")

    types = Counter(item.get("type", "text") for item in data)
    print("\n按类型统计:")
    for t, c in sorted(types.items()):
        print(f"  {t}: {c}")

    # 所有 image/chart 条目
    img_items = [item for item in data if item.get("type") in ("image", "chart")]
    print(f"\n独立图片/图表条目 (image/chart): {len(img_items)}")
    for i, item in enumerate(img_items):
        img_path = item.get("img_path", "")
        caption = str(item.get("caption", ""))[:60]
        print(f"  [{i}] type={item.get('type')}, img_path={img_path}, caption={caption}")

    # 所有 table 条目且带 img_path
    table_img_items = [item for item in data if item.get("type") == "table" and item.get("img_path")]
    print(f"\n表格条目带 img_path: {len(table_img_items)}")
    for item in table_img_items:
        print(f"  img_path={item.get('img_path')}, caption={str(item.get('table_caption',''))[:60]}")

    # 所有带 img_path 的条目（任意类型）
    all_with_img = [item for item in data if item.get("img_path")]
    print(f"\n所有带 img_path 的条目: {len(all_with_img)}")
    for item in all_with_img:
        print(f"  type={item.get('type')}, img_path={item.get('img_path')}")

# 实际移动到 .data/files/images 的图片
images_dir = Path(".data/files/images")
actual_images = list(images_dir.glob("*.*")) if images_dir.exists() else []
print(f"\n{'='*60}")
print(f".data/files/images 实际文件数: {len(actual_images)}")
for f in actual_images:
    print(f"  {f.name} ({f.stat().st_size} bytes)")
