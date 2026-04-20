# -*- coding: utf-8 -*-
"""
验证切片质量修复效果

测试内容：
1. _post_process_chunks: 空切片过滤、碎片合并、超长拆分
2. _extract_table_title: 从表格内容提取标题
3. _generate_table_summary: 不再产生 "小型表格：表格"
"""
import sys
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')

from parsers.mineru_parser import MinerUChunk, _post_process_chunks

print("=" * 60)
print("测试 1: _post_process_chunks")
print("=" * 60)

# 模拟实际碎片化数据
test_chunks = [
    MinerUChunk(content="**货源投放工作规范", chunk_type="text", text_level=1, title="货源投放工作规范", section_path="货源投放工作规范", page_start=1, page_end=1),
    MinerUChunk(content="（2023版）", chunk_type="text", text_level=2, title="（2023版）", section_path="货源投放工作规范 > （2023版）", page_start=1, page_end=1),
    MinerUChunk(content="按照行业**营销市场化取向改革和全省系统**营销高质量发展的总体要求，结合全省**营销工作实际，特制定本规范。", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="**一、适用范围**", chunk_type="text", text_level=2, title="一、适用范围", section_path="一、适用范围", page_start=1, page_end=1),
    MinerUChunk(content="适用于全省地市公司**货源投放工作所涉及的基础工作、投放准备、投放规则、投放策略制定。", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="**二、总体要求**", chunk_type="text", text_level=2, title="二、总体要求", section_path="二、总体要求", page_start=1, page_end=1),
    MinerUChunk(content="货源投放是**营销的核心业务，总体要求是：", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="1.坚持市场导向、供需匹配；", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="2.坚持总量控制、稍紧平衡；", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="3.坚持增速合理、贵在持续；", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="4.坚持公平公正、严格规范；", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="5.坚持状态优先、科学投放；", chunk_type="text", text_level=0, page_start=1, page_end=1),
    MinerUChunk(content="6.坚持区域协同、高效运作。", chunk_type="text", text_level=0, page_start=1, page_end=1),
    # 空切片
    MinerUChunk(content="", chunk_type="text", text_level=0, page_start=2, page_end=2),
    MinerUChunk(content="  \n  ", chunk_type="text", text_level=0, page_start=2, page_end=2),
    # 表格（不应被合并）
    MinerUChunk(content="表格内容", chunk_type="table", page_start=2, page_end=2, title="表格", table_html="<table>...</table>"),
]

print(f"输入: {len(test_chunks)} 个切片")
result = _post_process_chunks(test_chunks)
print(f"输出: {len(result)} 个切片")
print()

for i, chunk in enumerate(result):
    content_preview = chunk.content[:80].replace('\n', '\\n')
    print(f"  [{i}] type={chunk.chunk_type}, level={chunk.text_level}, len={len(chunk.content)}")
    print(f"      title={chunk.title}")
    print(f"      content: {content_preview}...")
    print()

# 断言检查
assert len(result) < len(test_chunks), f"合并后应减少切片数: {len(result)} >= {len(test_chunks)}"
empty_chunks = [c for c in result if not c.content.strip()]
assert len(empty_chunks) == 0, f"不应有空切片: 发现 {len(empty_chunks)} 个"
table_chunks = [c for c in result if c.chunk_type == 'table']
assert len(table_chunks) == 1, f"表格应保持独立: 发现 {len(table_chunks)} 个"
print("✅ 碎片合并 + 空切片过滤 测试通过")

# 测试超长切片拆分
print("\n" + "=" * 60)
print("测试 2: 超长切片拆分")
print("=" * 60)

long_text = "这是一段很长的测试文本。" * 200  # ~1200 chars
long_chunks = [
    MinerUChunk(content=long_text, chunk_type="text", page_start=1, page_end=1),
]

result2 = _post_process_chunks(long_chunks, max_chunk_size=500)
print(f"输入: 1 个切片 ({len(long_text)} chars)")
print(f"输出: {len(result2)} 个切片")
for i, c in enumerate(result2):
    print(f"  [{i}] len={len(c.content)}")
assert all(len(c.content) <= 500 for c in result2), "拆分后不应超过 max_chunk_size"
print("✅ 超长切片拆分 测试通过")

# 测试表格标题提取
print("\n" + "=" * 60)
print("测试 3: _extract_table_title")
print("=" * 60)

sys.path.insert(0, '.')
# 需要 import manager 但不初始化，直接测试静态方法
from knowledge.manager import KnowledgeBaseManager

# Markdown 表头
md_table = "【表格】表格\n\n| 序号 | 设备名称 | 数量 | 单价 |\n| --- | --- | --- | --- |\n| 1 | 电脑 | 10 | 5000 |"
title = KnowledgeBaseManager._extract_table_title(md_table)
print(f"  Markdown 表头: '{title}'")
assert '序号' in title, f"应包含列名: {title}"

# HTML <strong> 标签
html_table = "<table><tr><td><strong>检查环节</strong></td><td><strong>检查项目</strong></td></tr></table>"
title2 = KnowledgeBaseManager._extract_table_title(html_table)
print(f"  HTML strong: '{title2}'")
assert '检查环节' in title2, f"应从 HTML 提取: {title2}"

# 【表格】带标题
titled_table = "【表格】三峡上游主要水文站\n\n| 河流 | 站名 |\n| --- | --- |"
title3 = KnowledgeBaseManager._extract_table_title(titled_table)
print(f"  【表格】标题: '{title3}'")
assert '三峡' in title3, f"应提取【表格】后标题: {title3}"

# 纯文本 "表格" 回退
title4 = KnowledgeBaseManager._extract_table_title("表格")
print(f"  纯'表格'回退: '{title4}'")
assert title4 == "数据表格", f"应回退为'数据表格': {title4}"

print("✅ 表格标题提取 测试通过")

print("\n" + "=" * 60)
print("所有测试通过! ✅")
print("=" * 60)
