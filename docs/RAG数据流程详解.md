# RAG 数据流程详解

> 本文档详细梳理 RAG 系统从文档解析到最终响应的完整数据流，便于问题排查和系统优化。

---

## 一、整体架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           RAG 数据流程                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│  │ 文档上传  │───▶│ 文档解析  │───▶│ 切片入库  │───▶│ 向量检索  │         │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘         │
│       │              │              │              │                    │
│       ▼              ▼              ▼              ▼                    │
│   API 层         MinerU         ChromaDB       混合检索                 │
│   入口          解析器          向量库         BM25+向量                 │
│                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                          │
│  │ 图片匹配  │───▶│ LLM 生成  │───▶│ 响应输出  │                          │
│  └──────────┘    └──────────┘    └──────────┘                          │
│       │              │              │                                    │
│       ▼              ▼              ▼                                    │
│   相关性打分      AgenticRAG     SSE 流式                                │
│   图片选择         问答引擎                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、文档解析层

### 2.1 MinerU 解析输出结构

**入口函数**：`parsers/mineru_parser.py::parse_with_mineru()`

**输出文件**：
```
.data/mineru_temp/{file_hash}/
├── auto/
│   ├── {doc_name}.md              # Markdown 内容
│   ├── {doc_name}_content_list.json  # 结构化内容列表 ⭐
│   └── images/                    # 提取的图片
│       ├── abc123.jpg
│       └── def456.png
```

### 2.2 content_list.json 结构

这是 MinerU 解析的核心输出，包含文档的完整结构化信息：

```json
[
  {
    "type": "text",
    "text": "第一章 水情分析",
    "page_idx": 0,
    "bbox": [x0, y0, x1, y1],
    "text_level": 1
  },
  {
    "type": "text",
    "text": "正文内容...",
    "page_idx": 0,
    "bbox": [x0, y0, x1, y1],
    "text_level": 0
  },
  {
    "type": "table",
    "table_body": "<table>...</table>",
    "table_caption": "表1.1 数据统计",
    "img_path": "table_001.jpg",
    "page_idx": 1,
    "bbox": [x0, y0, x1, y1]
  },
  {
    "type": "image",
    "img_path": "abc123.jpg",
    "caption": "",                    // ⚠️ MinerU 未提取，通常为空
    "page_idx": 2,
    "bbox": [x0, y0, x1, y1]
  },
  {
    "type": "chart",
    "img_path": "chart_001.jpg",
    "caption": "",                    // ⚠️ 同样通常为空
    "page_idx": 3,
    "bbox": [x0, y0, x1, y1]
  }
]
```

### 2.3 content_list 各类型字段详解

| 类型 | 字段 | 说明 | 示例值 |
|------|------|------|--------|
| **text** | `text` | 文本内容 | "第一章 概述" |
| | `page_idx` | 页码索引（0-based） | 0 |
| | `bbox` | 边界框坐标 | [50, 100, 500, 150] |
| | `text_level` | 标题级别（0=正文，1=h1...） | 1 |
| **table** | `table_body` | 表格 HTML | `"<table>...</table>"` |
| | `table_caption` | 表格标题 | "表1.1 统计数据" |
| | `img_path` | 表格图片路径（可选） | "table_001.jpg" |
| **image** | `img_path` | 图片路径 | "abc123.jpg" |
| | `caption` | 图片标题 ⚠️ | "" (通常为空) |
| **chart** | `img_path` | 图表图片路径 | "chart_001.jpg" |
| | `caption` | 图表标题 ⚠️ | "" (通常为空) |

### 2.4 MinerUChunk 数据结构

**定义位置**：`parsers/mineru_parser.py` 第 95-116 行

```python
@dataclass
class MinerUChunk:
    content: str                      # 文本内容
    chunk_type: str                   # 类型: text, table, image, chart, equation
    page_start: int = 1               # 起始页码
    page_end: int = 1                 # 结束页码
    text_level: int = 0               # 标题级别 (0=body, 1=h1, 2=h2...)
    title: str = ""                   # 标题文本
    section_path: str = ""            # 章节路径 "第一章 > 1.1 概述"
    bbox: Optional[List[float]] = None  # 边界框 [x0, y0, x1, y1]
    source_file: str = ""             # 源文件名
    table_html: Optional[str] = None  # 表格 HTML（如果是表格）
    image_path: Optional[str] = None  # 图片路径（独立图片）
    images: Optional[List[Dict]] = None  # 关联图片列表
```

---

## 三、切片入库层

### 3.1 入库流程

**入口函数**：`knowledge/manager.py::add_file_to_kb()`

**流程图**：
```
add_file_to_kb()
    │
    ├── parse_document() → 调用 MinerU 解析
    │
    ├── convert_to_rag_format() → 转换为 RAG 格式
    │
    └── 遍历 pages_content:
        │
        ├── 文本切片 → 生成 embedding → 存入 ChromaDB
        │
        ├── 表格切片 → 生成摘要 → 存入 ChromaDB
        │
        └── 图片切片 → 生成描述 → 存入 ChromaDB
```

### 3.2 文本切片存储

**代码位置**：`knowledge/manager.py` 第 1050-1150 行

```python
text_meta = {
    'source': filename,           # 源文件名
    'page': page_info.get('page', 0),  # 页码
    'chunk_type': 'text',         # 类型
    'section': section,           # 章节标题
    'section_path': section_path, # 章节路径
    'level': page_info.get('level', 0),  # 标题级别
    'doc_type': _get_doc_type(filename),  # 文档类型
    'has_table': False,
    **extra_metadata
}

# document 字段 = 文本内容
document = page_info.get('text', '')

# 向量化
vector = embedding_model.encode(document).tolist()

collection.add(
    ids=[chunk_id],
    embeddings=[vector],
    documents=[document],         # ⭐ 文本内容
    metadatas=[text_meta]
)
```

### 3.3 表格切片存储

**代码位置**：`knowledge/manager.py` 第 1150-1200 行

```python
table_meta = {
    'source': filename,
    'page': page_info.get('page', 0),
    'chunk_type': 'table',
    'section': section,
    'caption': caption,           # 表格标题
    'has_table': True,
    'table_html': table_html,     # 表格 HTML
    ...
}

# document 字段 = 表格摘要（LLM 生成）或表格 Markdown
document = summary if summary else markdown_table

collection.add(
    ids=[chunk_id],
    embeddings=[vector],
    documents=[document],         # ⭐ 表格摘要/Markdown
    metadatas=[table_meta]
)
```

### 3.4 图片切片存储（重点！）

**代码位置**：`knowledge/manager.py` 第 1195-1255 行

```python
# caption 获取（问题根源！）
caption = page_info.get('caption') or chunk.title  # ⚠️ 两者都是默认值

# 元数据
image_meta = {
    'source': filename,
    'page': page_info.get('page', 0),
    'chunk_type': 'image',        # 或 'chart'
    'section': section_path,
    'caption': caption,           # ⚠️ 存入默认值 "图片"/"图表"
    'figure_number': _extract_figure_number(caption, section),  # 图号
    'image_path': image_path,     # 图片路径
    'has_vlm_desc': False,
    ...
}

# ⭐ document 字段 = 轻量级描述（正确！）
description = self.generate_lightweight_image_description(full_image_path, chunk, page_info)
# 结果: "图表：位于「第一章」> 1.1 概述，第5页"

# 向量化
vector = embedding_model.encode(description).tolist()

collection.add(
    ids=[chunk_id],
    embeddings=[vector],
    documents=[description],      # ⭐ 正确的描述信息
    metadatas=[image_meta]        # ⚠️ caption 是默认值
)
```

### 3.5 generate_lightweight_image_description 函数

**代码位置**：`knowledge/manager.py` 第 1418-1459 行

```python
def generate_lightweight_image_description(self, image_path: str, chunk, page_info: dict) -> str:
    """
    生成轻量级图片描述（不用 VLM）

    信息来源：文件名 + 标题/caption + 章节路径 + 页码
    """
    parts = []

    # 1. 图片类型
    chunk_type = page_info.get('chunk_type', 'image')
    type_label = "图表" if chunk_type == 'chart' else "图片"

    # 2. 标题或 caption
    title = chunk.title if hasattr(chunk, 'title') and chunk.title else ""
    caption = page_info.get('caption', '')

    # 3. 章节路径
    section = page_info.get('section_path', '') or page_info.get('section', '')

    # 4. 页码
    page = page_info.get('page', 0)

    # 组装描述
    if caption:
        parts.append(caption)
    elif title and title not in ("图片", "图表"):
        parts.append(title)

    if section:
        parts.append(f"位于「{section}」")

    parts.append(f"第{page}页")

    return f"{type_label}：{'，'.join(parts)}"
    # 输出示例: "图表：位于「Tracing the s-Process」> 2.1 The M-S-C sequence，第5页"
```

---

## 四、向量库结构

### 4.1 ChromaDB 存储结构

每个切片包含三个核心字段：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `ids` | str | 切片唯一 ID | "doc.pdf_text_0" |
| `embeddings` | List[float] | 向量表示 | [0.1, 0.2, ...] |
| `documents` | str | 文本内容/描述 | "图表：位于「xxx」第5页" |
| `metadatas` | dict | 元数据 | 见下表 |

### 4.2 元数据字段详解

#### 文本切片 metadata

```python
{
    'source': 'report.pdf',        # 源文件名
    'page': 5,                     # 页码
    'chunk_type': 'text',          # 类型
    'section': '水情分析',          # 章节标题
    'section_path': '第一章 > 1.1 水情分析',  # 章节路径
    'level': 0,                    # 标题级别
    'doc_type': 'pdf',             # 文档类型
    'has_table': False,
    'collection': 'public_kb'
}
```

#### 表格切片 metadata

```python
{
    'source': 'report.pdf',
    'page': 6,
    'chunk_type': 'table',
    'section': '数据统计',
    'caption': '表1.1 月度统计数据',  # 表格标题
    'has_table': True,
    'table_html': '<table>...</table>',  # 表格 HTML
    'collection': 'public_kb'
}
```

#### 图片/图表切片 metadata

```python
{
    'source': 'report.pdf',
    'page': 7,
    'chunk_type': 'image',         # 或 'chart'
    'section': '水情分析',
    'caption': '图片',              # 默认值（从 MinerU 获取）
    'figure_number': '',           # 图号（依赖 caption）
    'image_path': 'abc123.jpg',    # 图片路径
    'has_vlm_desc': False,         # 是否有 VLM 描述
    'bbox': '[x0,y0,x1,y1]',       # 边界框 JSON
    'preview': '图表：位于「第一章」...',  # 预览文本
    'collection': 'public_kb'
}
```

#### 图片切片 document 字段（优化后）

```python
# 优化后的 document 字段包含上下文，便于语义检索命中
"""
图表：位于「第一章 > 水情分析」，第5页
前文：2022年汛期长江流域出现汛期反枯，三峡水库出入库流量呈现明显下降趋势...
后文：由图2.1可见，水位呈现先升后降趋势，最高水位出现在8月中旬...
"""
```

---

## 五、检索层

### 5.1 混合检索流程

**入口**：`core/engine.py::search_knowledge()` 或 `core/agentic.py`

```
search_knowledge(query)
    │
    ├── 向量检索 (ChromaDB)
    │   └── collection.query(query_embeddings=[vector], n_results=20)
    │
    ├── 关键词检索 (BM25)
    │   └── bm25_index.search(query, top_k=20)
    │
    └── 结果合并 (RRF)
        └── reciprocal_rank_fusion(vector_results, bm25_results)
```

### 5.2 检索结果结构

```python
{
    'ids': ['doc.pdf_text_0', 'doc.pdf_image_1', ...],
    'documents': ['文本内容...', '图表：位于「xxx」第5页', ...],
    'metadatas': [{...}, {...}, ...],
    'distances': [0.1, 0.2, ...]
}
```

转换为 `contexts` 格式：
```python
contexts = [
    {
        'id': 'doc.pdf_text_0',
        'doc': '文本内容...',
        'meta': {...},
        'score': 0.9
    },
    {
        'id': 'doc.pdf_image_1',
        'doc': '图表：位于「xxx」第5页',  # ⭐ document 字段
        'meta': {
            'chunk_type': 'image',
            'caption': '图片',          # ⚠️ 默认值
            'image_path': 'abc.jpg',
            ...
        },
        'score': 0.85
    }
]
```

---

## 六、图片匹配层

### 6.1 图片选择流程

**代码位置**：`api/chat_routes.py` 第 246-293 行

```python
def select_images(contexts: list, query: str) -> list:
    """
    选择要展示的图片（打分排序 + 预算控制）
    """
    scored_images = []
    for ctx in contexts:
        meta = ctx.get('meta', {})
        if meta.get('chunk_type') in ('image', 'chart') and meta.get('image_path'):
            # 调用打分函数
            s = score_image_relevance(query, meta)  # ⚠️ 未传入 doc 字段
            if s >= MIN_SCORE:
                scored_images.append({
                    'score': s,
                    'id': os.path.basename(meta['image_path']),
                    'url': f"/images/{os.path.basename(meta['image_path'])}",
                    'type': meta['chunk_type'],
                    'source': meta.get('source'),
                    'page': meta.get('page'),
                    'description': ctx.get('doc', '')[:100]
                })

    scored_images.sort(key=lambda x: x['score'], reverse=True)
    return scored_images[:MAX_IMAGES]
```

### 6.2 图片相关性打分

**代码位置**：`api/chat_routes.py` 第 186-243 行

```python
def score_image_relevance(query: str, meta: dict) -> float:
    """
    图片相关性打分

    问题：使用 meta.get('caption') 获取的是默认值 "图片"/"图表"
    解决：应该使用 ctx['doc'] 字段进行匹配
    """
    score = 0.0

    # 1. 检测查询中的图片编号
    caption = meta.get('caption', '') or ''  # ⚠️ 获取默认值
    figure_matches = re.findall(r'图\s*(\d+\.?\d*)', query)

    if figure_matches:
        for fig_num in figure_matches:
            if f"图{fig_num}" in caption:  # ⚠️ 永远不匹配
                score += 5.0

    # 2. 查询内容与图片 caption 匹配
    if caption:
        overlap = len(set(query) & set(caption))  # ⚠<arg_value> 使用默认值匹配
        score += min(overlap * 0.15, 3.0)

    # ... 其他加分逻辑

    return score
```

---

## 七、问题排查指南

### 7.1 常见问题定位

| 问题现象 | 可能原因 | 排查位置 |
|----------|----------|----------|
| 图片不显示 | caption 为默认值 | 检索结果 `meta['caption']` |
| 图片匹配错误 | 打分逻辑未使用 doc 字段 | `score_image_relevance()` |
| 表格未识别 | table_html 为空 | 检索结果 `meta['table_html']` |
| 切片丢失 | 解析失败或过滤 | MinerU 输出 `content_list.json` |

### 7.2 调试命令

```python
# 1. 查看 MinerU 解析结果
import json
with open('.data/mineru_temp/{hash}/auto/{doc}_content_list.json') as f:
    content_list = json.load(f)
    for item in content_list[:10]:
        print(f"类型: {item.get('type')}, 内容: {str(item)[:100]}")

# 2. 查看向量库切片
from knowledge.manager import KnowledgeBaseManager
kb = KnowledgeBaseManager()
collection = kb.get_collection('public_kb')

# 获取所有图片切片
result = collection.get(
    where={"chunk_type": "image"},
    include=['documents', 'metadatas']
)

for i, (doc, meta) in enumerate(zip(result['documents'][:5], result['metadatas'][:5])):
    print(f"图片 {i+1}:")
    print(f"  document: {doc}")
    print(f"  caption: {meta.get('caption')}")
    print(f"  image_path: {meta.get('image_path')}")
```

### 7.3 数据流检查清单

```
□ MinerU 解析
  ├─ content_list.json 是否生成？
  ├─ 图片项 caption 字段是否为空？
  └─ 图片文件是否正确提取？

□ 切片入库
  ├─ document 字段是否包含描述？
  ├─ metadata.caption 是否为默认值？
  └─ image_path 是否正确？

□ 向量检索
  ├─ 检索结果是否包含图片切片？
  ├─ ctx['doc'] 是否有值？
  └─ ctx['meta']['caption'] 是什么？

□ 图片匹配
  ├─ score_image_relevance 是否使用 doc 字段？
  └─ 最终匹配分数是否足够？
```

---

## 八、已知问题与解决方案

### 8.1 图片 caption 为默认值

**问题**：MinerU 未提取图片标题，导致 `meta['caption']` 为 "图片"/"图表"

**影响**：`score_image_relevance()` 无法正确匹配图片

**临时解决**：修改 `score_image_relevance()` 使用 `ctx['doc']` 字段

**长期解决**：在 MinerU 解析层从文档上下文提取图片标题

### 8.2 figure_number 未提取

**问题**：图号提取依赖 caption，caption 为空时 figure_number 也为空

**影响**：无法按图号精确检索

**解决**：改进 `_extract_figure_number()` 从 section 或上下文提取

---

## 九、参考文件

| 文件 | 作用 | 关键函数 |
|------|------|----------|
| `parsers/mineru_parser.py` | 文档解析 | `parse_with_mineru()`, `MinerUChunk` |
| `knowledge/manager.py` | 切片入库 | `add_file_to_kb()`, `generate_lightweight_image_description()` |
| `api/chat_routes.py` | 图片匹配 | `select_images()`, `score_image_relevance()` |
| `core/engine.py` | 向量检索 | `search_knowledge()` |
| `core/agentic.py` | 问答引擎 | `AgenticRAG` |
