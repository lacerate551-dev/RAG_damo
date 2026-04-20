# -*- coding: utf-8 -*-
"""检查 MinerU 输出中表格的实际内容"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE = r"c:\Users\qq318\Desktop\rag-agent\.data\mineru_output"

# hash -> 文件名映射
hash_map = {}
for h in os.listdir(BASE):
    subdir = os.path.join(BASE, h)
    for name in os.listdir(subdir):
        hash_map[h] = name

print("=" * 60)
print("MinerU 表格内容分析")
print("=" * 60)

for file_hash, doc_name in hash_map.items():
    # 查找 content_list
    for subpath in ["office", "auto"]:
        cl_path = os.path.join(BASE, file_hash, doc_name, subpath, f"{doc_name}_content_list.json")
        if os.path.exists(cl_path):
            break
    else:
        print(f"\n{doc_name}: content_list not found")
        continue

    with open(cl_path, 'r', encoding='utf-8') as f:
        content_list = json.load(f)

    tables = [(i, item) for i, item in enumerate(content_list) if item.get('type') == 'table']
    
    if not tables:
        continue

    print(f"\n--- {doc_name} ({len(tables)} tables) ---")
    
    no_caption = 0
    no_body = 0
    
    for idx, item in tables:
        caption = item.get('table_caption', '')
        if isinstance(caption, list):
            caption = ' '.join(str(c) for c in caption)
        body = item.get('table_body', '')
        if isinstance(body, list):
            body = ' '.join(str(b) for b in body)
        page = item.get('page_idx', '?')
        
        has_caption = bool(caption and str(caption).strip() and str(caption).strip() != '表格')
        has_body = bool(body and str(body).strip())
        
        if not has_caption:
            no_caption += 1
        if not has_body:
            no_body += 1
        
        # 只打印前5个无caption的
        if not has_caption and no_caption <= 5:
            body_preview = body[:120].replace('\n', '\\n') if body else '(empty)'
            print(f"  [idx={idx}, page={page}] caption={repr(caption)[:40]}")
            print(f"    body: {body_preview}")
    
    print(f"  总表格数: {len(tables)}")
    print(f"  无caption: {no_caption}")
    print(f"  无body: {no_body}")
    print(f"  有caption有body: {len(tables) - max(no_caption, no_body)}")
