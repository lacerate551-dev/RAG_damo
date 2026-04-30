# RAG 数据流程完整分析

> 本文档详细分析 RAG 系统从文档上传到回答生成的完整数据流程，
> 帮助理解各模块职责和定位问题。

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户查询                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  api/chat_routes.py - generate()                                        │
│  ├── 意图分析 (intent_analyzer.py) - 问题改写 + 是否需要检索              │
│  ├── 混合检索 (search_hybrid → engine.search_knowledge)                  │
│  ├── 图片选择 (select_images) - 打分排序                                 │
│  └── LLM 生成回答                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、文档入库流程

### 2.1 解析层 (parsers/mineru_parser.py)

**输入**：PDF/Word/Excel 文件

**核心函数**：`parse_with_mineru()`

**处理流程**：
1. MinerU 解析文档 → 输出 `content_list.json` + 图片文件
2. 遍历 content_list，按类型处理：

| item_type | 处理方式 | MinerUChunk 字段 |
|-----------|----------|------------------|
| `text` | 文本块 | content, section_path, text_level |
| `table` | 表格 | content, table_html, image_path(表格图片) |
| `image` | 图片 | content(=caption), image_path, context_before/after |
| `chart` | 图表 | content(=caption), image_path, context_before/after |

**图片上下文提取** (第 366-384 行)：
```python
def get_context_for_image(image_idx: int, page_idx: int, window: int = 3) -> tuple:
    """获取图片前后的文本上下文"""
    context_before = []
    context_after = []

    # 查找图片前后的文本项
    for item_idx, text, item_page in text_items:
        if item_idx < image_idx and item_page >= page_idx - 1:
            context_before.append(text)  # 图片之前的文本
        elif item_idx > image_idx and item_page <= page_idx + 1:
            context_after.append(text)   # 图片之后的文本

    # 只保留最近的 window 条
    return " ".join(context_before[-window:]), " ".join(context_after[:window])
```

**输出**：`MinerUChunk` 列表

```python
@dataclass
class MinerUChunk:
    content: str                      # 文本内容（图片类型通常是 caption 或默认值）
    chunk_type: str                   # 类型: text, table, image, chart
    page_start: int = 1               # 起始页码
    page_end: int = 1                 # 结束页码
    text_level: int = 0               # 标题级别 (0=body, 1=h1, 2=h2...)
    title: str = ""                   # 标题文本
    section_path: str = ""            # 章节路径
    bbox: Optional[List[float]] = None  # 边界框
    source_file: str = ""             # 源文件名
    table_html: Optional[str] = None  # 表格 HTML
    image_path: Optional[str] = None  # 图片路径
    images: Optional[List[Dict]] = None  # 关联图片列表
    context_before: str = ""          # 图片前的文本上下文
    context_after: str = ""           # 图片后的文本上下文
```

---

### 2.2 入库层 (knowledge/manager.py)

**核心函数**：`add_file_to_kb()`

**处理流程**：

```
MinerUChunk 列表
       │
       ├── 文本块 ──────────────────────► 文本切片入库
       │   ├── 计算 embedding
       │   └── collection.add(id, embedding, document, metadata)
       │
       ├── 表格块 ──────────────────────► 表格切片入库
       │   ├── 生成语义增强内容
       │   └── collection.add(...)
       │
       └── 图片块 ──────────────────────► 图片切片入库
           ├── 检查 VLM 缓存（新增）
           ├── 生成描述（VLM 或轻量描述）
           └── collection.add(...)
```

**图片切片入库详细流程** (第 1296-1378 行)：

```python
# 1. 检查 VLM 缓存（优先使用）
vlm_desc = self._get_vlm_cache(full_image_path)

if vlm_desc:
    # 使用 VLM 描述（语义更丰富）
    description = vlm_desc
    image_meta['has_vlm_desc'] = True
else:
    # 生成轻量描述（包含上下文）
    description = self.generate_lightweight_image_description(...)

# 2. 计算 embedding
vector = embedding_model.encode(description).tolist()

# 3. 存入向量库
collection.add(
    ids=[chunk_id],
    embeddings=[vector],
    documents=[description],
    metadatas=[image_meta]
)
```

**generate_lightweight_image_description() 输出格式**：

```
图表：图2.3，位于「... > 2.3发电」，第12页
前文：受长江流域性严重枯水影响，2022 年三峡电站年度发电量为 787.90 亿千瓦时...
后文：2.4航运 三峡船闸和葛洲坝船闸实行统一调度...
```

**VLM 缓存描述格式**（更精准）：

```
图2.3 柱状图 主要内容描述：该柱状图展示了2003年至2022年每年的发电量（单位：亿千瓦时）。
发电量在2003年为86.07亿千瓦时，随后逐年波动上升，至2020年达到峰值1118.02亿千瓦时...
```

---

### 2.3 向量库存储结构

**ChromaDB 存储字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ids` | str | 切片唯一标识，如 `三峡公报_1-15页.pdf_text_24` |
| `embeddings` | List[float] | 768 维向量（bge-base-zh-v1.5） |
| `documents` | str | 切片内容（用于 LLM 上下文和相似度计算） |
| `metadatas` | dict | 元数据 |

**图片切片 metadata 字段**：

```python
{
    'source': '三峡公报_1-15页.pdf',
    'page': 12,
    'chunk_type': 'chart',           # image 或 chart
    'section': '综述 > 2.3发电',
    'caption': '图表',               # 通常为默认值
    'figure_number': '2.3',          # 从上下文提取的图号
    'image_path': 'ab77281e7913.jpg',
    'has_vlm_desc': True,            # 是否有 VLM 描述
    'preview': '图2.3 柱状图 主要内容...'  # 描述预览
}
```

---

## 三、检索流程

### 3.1 混合检索 (core/engine.py)

**核心函数**：`search_knowledge()`

**流程图**：

```
用户查询
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. 查询缓存检查                                                  │
│    cache.get_query_result(query, kb_name)                       │
└─────────────────────────────────────────────────────────────────┘
    │ 未命中
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 向量检索                                                      │
│    query_vector = embedding_model.encode(query)                  │
│    collection.query(query_embeddings=[query_vector], n_results=100) │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. BM25 关键词检索（可选）                                        │
│    bm25_results = bm25_index.search(query, top_k=100)           │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. RRF 融合                                                      │
│    fused_results = reciprocal_rank_fusion([vector, bm25], weights) │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. MMR 去重                                                      │
│    fused_results = _apply_mmr(query, fused_results, top_k=30)   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Rerank 重排序                                                 │
│    rerank_results(query, fused_results, top_k=5)                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. 返回结果                                                      │
│    {ids: [[...]], documents: [[...]], metadatas: [[...]],       │
│     distances: [[...]]}                                          │
└─────────────────────────────────────────────────────────────────┘
```

**关键参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `recall_k` | 100 | 召回候选数量 |
| `top_k` | 5-20 | 最终返回数量 |
| `VECTOR_WEIGHT` | 0.6 | 向量检索权重 |
| `BM25_WEIGHT` | 0.4 | BM25 检索权重 |

---

### 3.2 图片选择 (api/chat_routes.py)

**核心函数**：`select_images()`

**流程**：

```
检索结果 contexts
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. 提取图表引用                                                   │
│    从 top 5 文本块提取 "见图2.3"、"如表2.2" 等                     │
│    → referenced_figures = {'2.3': {来源文件}}                    │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 遍历图片切片，打分                                             │
│    for ctx in contexts:                                          │
│        if ctx['meta']['chunk_type'] in ('image', 'chart'):      │
│            score = score_image_relevance(query, meta, doc)      │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. 排序返回 top N                                                │
│    scored_images.sort(key=lambda x: x['score'], reverse=True)   │
│    return scored_images[:MAX_IMAGES]                            │
└─────────────────────────────────────────────────────────────────┘
```

**score_image_relevance() 打分逻辑**：

| 匹配项 | 加分 |
|--------|------|
| 图号精确匹配（查询中有"图2.3"） | +10 分 |
| 表号精确匹配 | +10 分 |
| 关键词匹配（"发电量"等） | +2 分/个 |
| 字符重叠 | +0.2 分/字符 |
| 章节匹配 | +1.5 分 |
| 图片类型（chart > image） | +2 / +1 分 |
| 向量相似度 | +2 分（最高） |

---

## 四、问题诊断

### 4.1 问题现象

用户查询"蓄水以来逐年发电量"，期望返回图2.3，实际返回图2.5/表2.2。

### 4.2 诊断结果

| 排名 | 类型 | 内容 | Distance | 问题 |
|------|------|------|----------|------|
| 1 | text | "2.3发电"章节文本 | 0.9980 | ✅ 正确 |
| 24 | image | 封面图片 | 0.0002 | ❌ 极低 |
| N/A | chart | 图2.3 | 未进入 top 50 | ❌ 极低 |

### 4.3 根因分析

**问题 1：图片切片向量相似度极低**

- 图片的 `document` 是轻量描述格式
- 关键词"发电量"出现在"前文"中，被大量上下文稀释
- embedding 模型对这种格式的内容相似度计算不准确

**问题 2：VLM 缓存未被利用**

- 已有 VLM 缓存包含精准描述："展示了2003年至2022年每年的发电量"
- 但入库时未检查 VLM 缓存
- 导致图片切片的语义表达不准确

**问题 3：文本切片覆盖图片语义**

- "2.3发电" 章节的文本切片包含完整描述
- 文本切片排名靠前，但没有关联图片
- 图片切片独立存在，无法通过文本切片找到

---

## 五、优化方案

### 5.1 P0：入库时使用 VLM 缓存（已实现）

**修改文件**：`knowledge/manager.py`

**方案**：
```python
# 优先使用 VLM 缓存
vlm_desc = self._get_vlm_cache(full_image_path)

if vlm_desc:
    description = vlm_desc  # 使用 VLM 描述
    image_meta['has_vlm_desc'] = True
else:
    description = self.generate_lightweight_image_description(...)  # 轻量描述

vector = embedding_model.encode(description).tolist()
```

**验证结果**（2026-04-28）：
- 为图2.3 生成了 VLM 描述，包含关键词"发电量"、"柱状图"、"2003年至2022年每年"
- 更新向量库后，查询"蓄水以来逐年发电量"时图2.3 排名第2（distance=0.3153）
- 效果显著提升

### 5.2 P1：意图分析器优化（已实现）

**问题**：用户再次问相同问题时，意图分析器错误设置 `need_retrieval=False`，导致复用错误的上下文。

**修改文件**：`core/intent_analyzer.py`

**方案**：在 SYSTEM_PROMPT 中添加规则：
- **当用户重复提问相同或相似问题时，必须设置 need_retrieval = true**
- 原因：用户可能对之前的回答不满意，或之前的回答包含错误信息

### 5.3 P2：建立图文关联索引

**方案**：
1. 文本切片存储时，提取其中的图表引用
2. 在 metadata 中记录 `referenced_images: ["图2.3"]`
3. 检索时，通过文本切片的 `referenced_images` 找到对应图片

### 5.4 P3：图片独立召回通道

**方案**：
1. 向量检索时，对图片切片使用独立的 top_k
2. 保证图片切片有足够的召回机会
3. 最终融合文本和图片结果

---

## 六、验证方案

### 6.1 重建向量库

```bash
# 方式1：删除向量库目录后同步
rm -rf knowledge/vector_store/chroma/public_kb
curl -X POST http://localhost:5001/sync

# 方式2：通过 API 重新上传文档
```

### 6.2 测试检索

```bash
# 测试 1：关键词查询
curl -X POST http://localhost:5001/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "蓄水以来逐年发电量"}'
# 预期：图2.3 排名靠前

# 测试 2：图号查询
curl -X POST http://localhost:5001/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "图2.3 发电量"}'
# 预期：精确返回图2.3

# 测试 3：语义查询
curl -X POST http://localhost:5001/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "三峡水库补水统计"}'
# 预期：返回表2.2/图2.5
```

### 6.3 检查向量库内容

```python
import chromadb
client = chromadb.PersistentClient(path='knowledge/vector_store/chroma/public_kb')
col = client.get_collection('public_kb')

# 查看图片切片
results = col.get(
    where={'chunk_type': {'$in': ['image', 'chart']}},
    include=['metadatas', 'documents'],
    limit=10
)

for i, chunk_id in enumerate(results['ids']):
    meta = results['metadatas'][i]
    doc = results['documents'][i]
    print(f"[{i+1}] {meta.get('chunk_type')} | has_vlm_desc: {meta.get('has_vlm_desc')}")
    print(f"    Doc: {doc[:100]}...")
```

---

## 七、关键文件索引

| 文件 | 职责 | 关键函数 |
|------|------|----------|
| `parsers/mineru_parser.py` | 文档解析 | `parse_with_mineru()`, `get_context_for_image()` |
| `knowledge/manager.py` | 向量库管理 | `add_file_to_kb()`, `generate_lightweight_image_description()`, `_get_vlm_cache()` |
| `core/engine.py` | 检索引擎 | `search_knowledge()`, `reciprocal_rank_fusion()`, `rerank_results()` |
| `api/chat_routes.py` | API 路由 | `generate()`, `select_images()`, `score_image_relevance()` |
| `core/intent_analyzer.py` | 意图分析 | `analyze()`, `IntentAnalysis` |
| `knowledge/lazy_enhance.py` | 懒加载增强 | `lazy_vlm_description()`, `enhance_retrieved_chunks()` |
