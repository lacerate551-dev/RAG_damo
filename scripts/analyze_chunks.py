# -*- coding: utf-8 -*-
"""分析 exported_chunks_v2 中的切片质量"""
import re
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE = r"c:\Users\qq318\Desktop\rag-agent\exported_chunks_v2\public_kb"

print("=" * 60)
print("切片质量分析报告")
print("=" * 60)

for fname in os.listdir(BASE):
    if not fname.endswith('.md') or fname.startswith('_'):
        continue
    
    fpath = os.path.join(BASE, fname)
    with open(fpath, encoding='utf-8') as f:
        data = f.read()
    
    # 提取所有 Length
    lengths = [int(m) for m in re.findall(r'\*\*Length\*\*: (\d+) chars', data)]
    
    if not lengths:
        print(f"\n{fname}: 未找到 Length 字段")
        continue
    
    print(f"\n--- {fname} ---")
    print(f"  总切片数: {len(lengths)}")
    print(f"  最大: {max(lengths)}, 最小: {min(lengths)}, 平均: {sum(lengths)/len(lengths):.0f}")
    print(f"  空(0字符): {sum(1 for l in lengths if l == 0)}")
    print(f"  微短(<10字符): {sum(1 for l in lengths if l < 10)}")
    print(f"  短(<20字符): {sum(1 for l in lengths if l < 20)}")
    print(f"  短(<50字符): {sum(1 for l in lengths if l < 50)}")
    print(f"  超长(>1000字符): {sum(1 for l in lengths if l > 1000)}")
    print(f"  巨型(>2000字符): {sum(1 for l in lengths if l > 2000)}")
    print(f"  巨型(>3000字符): {sum(1 for l in lengths if l > 3000)}")
    
    # 小型表格统计
    bad_table = data.count('小型表格：表格')
    empty_table_count = len(re.findall(r'小型表格：\s*```', data))
    good_table = len(re.findall(r'小型表格：\S', data)) - bad_table
    
    if bad_table or empty_table_count or good_table:
        print(f"  [表格摘要] 有意义: {good_table}, 无意义(仅'表格'): {bad_table}, 空标题: {empty_table_count}")
    
    # 列出 top 5 最大切片
    if max(lengths) > 1000:
        sorted_l = sorted(enumerate(lengths), key=lambda x: x[1], reverse=True)
        print(f"  Top 5 最大切片:")
        for idx, size in sorted_l[:5]:
            print(f"    Chunk index {idx}: {size} chars")

print("\n" + "=" * 60)
