# RAG幻觉问题优化方案

本文档分析RAG（检索增强生成）系统中幻觉问题产生的原因，并提供对应的解决方案。

---

## 一、什么是RAG幻觉？

RAG幻觉是指大模型在基于检索到的知识库内容回答问题时，产生了以下问题：
- 编造了知识库中不存在的信息
- 给出了错误的答案
- 混淆了不同来源的信息
- 无法正确引用来源

---

## 二、幻觉产生的七大原因

### 1. 检索失效

**问题描述：**

用户的提问往往是口语化、模糊的，直接检索可能找不到相关内容，大模型就会"自己编"。

**示例：**
```
用户问题: "那东西怎么用？"
向量检索: 找不到匹配内容（问题太模糊）
大模型行为: 开始编造答案
```

**产生原因：**
| 原因 | 说明 |
|------|------|
| 语义鸿沟 | 用户表达与文档表述差异大 |
| 词汇不匹配 | 同义词、近义词未被识别 |
| 问题不完整 | 缺少上下文信息 |

---

### 2. 多跳推理难题

**问题描述：**

复杂问题需要多次检索、逐步推理，传统RAG难以处理。

**示例：**
```
用户问题: "A公司CEO的妻子的母校在哪里？"

传统检索会分别检索:
- "A公司" → 找到公司信息
- "CEO" → 找到CEO相关信息
- "妻子" → 找不到相关信息
- "母校" → 找不到相关信息

最终答案缺失关键环节，大模型开始猜测。
```

**产生原因：**
- 单次检索无法获取完整信息链
- 实体关系未被建模
- 推理路径不明确

---

### 3. 上下文迷失

**问题描述：**

检索返回大量片段，但相关内容被噪声淹没，大模型"看漏了"关键信息。

**示例：**
```
检索返回10个片段:
- 片段1-3: 相关度高
- 片段4-7: 相关度低（噪声）
- 片段8-10: 相关度中

问题: 关键信息在片段2，但被噪声干扰，大模型关注了错误内容。
```

**产生原因：**
| 原因 | 说明 |
|------|------|
| 召回数量不当 | top_k过大或过小 |
| 排序不准确 | 向量相似度≠语义相关度 |
| 上下文过长 | 超出模型有效注意力范围 |

---

### 4. 大模型"固执"问题

**问题描述：**

大模型的参数化记忆（训练数据）覆盖了检索到的事实内容。

**示例：**
```
知识库内容: "公司成立于2018年"
大模型训练数据: "该公司成立于2015年"

结果: 大模型可能回答"2015年"，因为它"记得"这个信息。
```

**产生原因：**
- 大模型对训练数据有"偏好"
- Prompt约束不够强
- 模型倾向于"自信"地回答

---

### 5. 知识库质量问题

**问题描述：**

知识库本身存在问题，导致大模型基于错误信息回答。

**产生原因：**
| 问题 | 说明 |
|------|------|
| 文档解析错误 | PDF解析丢失信息、表格格式错乱 |
| 切片不当 | 切断语义完整性，丢失上下文 |
| 向量化信息丢失 | 重要信息在向量化过程中损失 |
| 数据过时 | 知识库内容未更新 |

---

### 6. 检索结果冲突

**问题描述：**

知识库中存在矛盾信息，大模型无法判断哪个正确。

**示例：**
```
文档A (2020年): 公司有200名员工
文档B (2023年): 公司有300名员工
文档C (无日期): 公司有256名员工

用户问: 公司有多少员工？
大模型: 随机选择一个回答，或编造新数字。
```

---

### 7. 时效性问题

**问题描述：**

知识库内容过时，但用户询问最新信息。

**示例：**
```
知识库: 2022年的政策文档
用户问题: "现在的政策是什么？"

问题: 大模型可能基于过时信息回答，或编造"最新"内容。
```

---

## 三、解决方案

### 方案1: Query预处理（解决检索失效）

**核心思路：** 在检索前，先用小模型优化用户问题。

#### 1.1 问题改写

```python
def rewr ite_query(original_query):
    """将口语化问题改写为标准检索语句"""
    prompt = f"""请将以下口语化问题改写为更清晰的检索语句。

原问题: {original_query}
改写后: """

    # 调用小模型改写
    rewritten = call_llm(prompt)
    return rewritten

# 示例
原始问题: "那东西怎么用？"
改写后: "智能手表X1的使用方法是什么？"
```

#### 1.2 同义词扩展（Query Expansion）

```python
def expand_query(query):
    """扩展同义词，生成多个检索词"""
    prompt = f"""请为以下问题生成3-5个语义相似的检索词/短语。

问题: {query}
同义词/相关词: """

    expansions = call_llm(prompt).split('\n')
    return expansions

# 示例
原始问题: "怎么操作？"
扩展词: ["操作方法", "使用教程", "操作指南", "说明书", "使用方法"]
```

#### 1.3 HyDE（假设文档生成）

```python
def hyde_retrieval(query):
    """先让模型猜测答案，再用猜测内容检索"""

    # 步骤1: 生成假设性答案
    prompt = f"""请猜测以下问题的答案（即使不确定也可以编造）。

问题: {query}
假设答案: """

    hypothetical_answer = call_llm(prompt)

    # 步骤2: 用假设答案检索（而非原问题）
    results = vector_search(hypothetical_answer)

    return results

# 原理: 假设答案与真实答案在向量空间中更接近
```

#### 1.4 多路检索融合

```python
def multi_path_retrieval(query):
    """多路检索，结果融合"""

    results = []

    # 路径1: 原问题检索
    results.append(vector_search(query))

    # 路径2: 改写问题检索
    rewritten = rewrite_query(query)
    results.append(vector_search(rewritten))

    # 路径3: 扩展词检索
    expansions = expand_query(query)
    for exp in expansions[:3]:
        results.append(vector_search(exp))

    # 融合结果（RRF算法）
    final_results = reciprocal_rank_fusion(results)

    return final_results
```

---

### 方案2: 迭代检索（解决多跳推理）

**核心思路：** 将复杂问题分解，多次检索，逐步推理。

```python
def iterative_retrieval(query):
    """迭代检索，处理多跳问题"""

    # 步骤1: 识别需要检索的实体
    entities = extract_entities(query)
    # 示例: ["A公司", "CEO", "妻子", "母校"]

    # 步骤2: 逐步检索
    context = {}

    # 第1跳: 检索A公司的CEO
    result1 = vector_search(f"A公司的CEO是谁")
    context["CEO"] = extract_answer(result1)  # → "张三"

    # 第2跳: 检索张三的妻子
    result2 = vector_search(f"{context['CEO']}的妻子")
    context["妻子"] = extract_answer(result2)  # → "李四"

    # 第3跳: 检索李四的母校
    result3 = vector_search(f"{context['妻子']}的母校")
    context["母校"] = extract_answer(result3)  # → "北京大学"

    return context

# 更智能的方式: 让大模型规划检索步骤
def agent_retrieval(query):
    """基于Agent的迭代检索"""

    prompt = f"""为了回答问题"{query}"，我需要检索哪些信息？请按顺序列出检索步骤。

步骤1: 检索什么？
步骤2: 基于步骤1的结果，检索什么？
..."""

    steps = call_llm(prompt)

    # 执行每一步
    for step in steps:
        result = vector_search(step)
        # 让模型决定下一步...
```

---

### 方案3: 重排序与压缩（解决上下文迷失）

#### 3.1 Rerank重排序

```python
from sentence_transformers import CrossEncoder

def rerank_results(query, initial_results, top_k=5):
    """对初步召回结果进行精排"""

    # 加载重排序模型
    reranker = CrossEncoder('BAAI/bge-reranker-base')

    # 构建查询-文档对
    pairs = [(query, doc) for doc in initial_results]

    # 计算精排分数
    scores = reranker.predict(pairs)

    # 按分数排序，取top_k
    ranked_results = sorted(
        zip(initial_results, scores),
        key=lambda x: x[1],
        reverse=True
    )[:top_k]

    return [r[0] for r in ranked_results]
```

**重排序模型推荐：**

| 模型 | 大小 | 效果 |
|------|------|------|
| `BAAI/bge-reranker-base` | 278M | 推荐，平衡 |
| `BAAI/bge-reranker-large` | 560M | 更准 |
| `BAAI/bge-reranker-v2-m3` | 560M | 多语言支持 |

#### 3.2 提示词压缩

```python
def compress_context(context, query):
    """压缩上下文，保留核心信息"""

    prompt = f"""请提取以下内容中与问题"{query}"最相关的核心信息，去除无关内容。

原始内容:
{context}

压缩后（保留关键信息，去除冗余）: """

    compressed = call_llm(prompt)
    return compressed

# 或使用专门的压缩工具如 LLMLingua
from llmlingua import PromptCompressor

def llmlingua_compress(context, query):
    compressor = PromptCompressor()
    compressed = compressor.compress_prompt(
        context,
        instruction=query,
        rate=0.5  # 压缩到50%
    )
    return compressed
```

---

### 方案4: 严格Prompt约束（解决大模型"固执"）

**优化前：**
```python
prompt = f"""你是一个智能助手，请根据参考资料回答问题。
参考资料: {context}
问题: {query}
回答: """
```

**优化后：**
```python
STRICT_PROMPT = """你是一个严谨的信息提取助手，请严格遵循以下规则：

【严格约束】
1. 只能基于【参考资料】中的信息回答，禁止使用你的先验知识
2. 若参考资料中没有答案，直接回复"参考资料中未找到相关信息"
3. 不要推测、不要补充、不要编造
4. 必须标注信息来源（文件名、页码等）

【回答格式】
- 答案: [基于资料的具体回答，引用原文]
- 来源: [文件名 第X页]
- 置信度: 高/中/低

【特殊情况处理】
- 如果参考资料中有矛盾信息，列出所有版本并标注来源
- 如果问题涉及时效性，提示用户"知识库日期为XXX，请核实最新信息"

【参考资料】
{context}

【用户问题】
{query}

请回答："""
```

---

### 方案5: 知识库质量优化

#### 5.1 语义切片

```python
from langchain.text_splitter import SemanticChunker

def semantic_chunking(text):
    """按语义边界切分，而非固定长度"""

    splitter = SemanticChunker(
        embedding_model,
        breakpoint_threshold_type="percentile"
    )

    chunks = splitter.split_text(text)
    return chunks

# 对比:
# 固定切分: ["表格如下：产品A销量100，产品B"] ["销量200，产品C..."]  ← 表格被切断
# 语义切分: ["表格: 产品A销量100，产品B销量200，产品C销量150"]  ← 完整保留
```

#### 5.2 多解析器对比

```python
def robust_pdf_parse(filepath):
    """多解析器对比，提高解析质量"""

    results = {}

    # 解析器1: pdfplumber
    try:
        text1 = parse_with_pdfplumber(filepath)
        results['pdfplumber'] = text1
    except:
        pass

    # 解析器2: PyMuPDF
    try:
        text2 = parse_with_pymupdf(filepath)
        results['pymupdf'] = text2
    except:
        pass

    # 解析器3: pypdf
    try:
        text3 = parse_with_pypdf(filepath)
        results['pypdf'] = text3
    except:
        pass

    # 选择最佳结果（如最长、最完整）
    best = max(results.values(), key=len)
    return best
```

---

### 方案6: 冲突检测与告知

```python
def detect_conflicts(results):
    """检测检索结果中的冲突信息"""

    # 提取数值型信息
    numbers = extract_numbers(results)

    # 检测矛盾
    conflicts = []
    for key, values in numbers.items():
        if len(set(values)) > 1:
            conflicts.append({
                'field': key,
                'values': values,
                'sources': [r['source'] for r in results if key in r]
            })

    return conflicts

def answer_with_conflict_detection(query, results):
    """回答时检测并告知冲突"""

    conflicts = detect_conflicts(results)

    if conflicts:
        conflict_info = "\n".join([
            f"- {c['field']}: 存在{len(c['values'])}个不同说法"
            for c in conflicts
        ])

        return f"""检测到知识库中存在矛盾信息：

{conflict_info}

以下是基于最早/最新文档的回答：
..."""

    return normal_answer(query, results)
```

---

### 方案7: 时效性管理

```python
def add_timestamp_metadata(documents):
    """为文档添加时间戳元数据"""

    for doc in documents:
        # 尝试从文件名提取日期
        date = extract_date_from_filename(doc['filename'])

        # 或从文件修改时间获取
        if not date:
            date = get_file_modified_time(doc['filepath'])

        doc['metadata']['doc_date'] = date
        doc['metadata']['indexed_date'] = datetime.now()

def search_with_freshness(query, prefer_recent=True):
    """检索时考虑文档时效性"""

    results = vector_search(query)

    # 按时效性排序
    if prefer_recent:
        results = sorted(
            results,
            key=lambda x: x['metadata'].get('doc_date', ''),
            reverse=True
        )

    return results
```

---

## 四、综合架构优化

### 优化后的完整流程

```
┌─────────────────────────────────────────────────────────────┐
│                      用户问题                                │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│              Query预处理层                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ 问题改写    │  │ 同义词扩展   │  │ HyDE假设文档生成    │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    混合检索层                                │
│  ┌─────────────────────┐   ┌─────────────────────────────┐ │
│  │ 向量检索            │   │ 关键词检索(BM25)            │ │
│  └──────────┬──────────┘   └──────────────┬──────────────┘ │
│             └──────────────┬───────────────┘                │
│                            ↓                                 │
│                   结果融合(RRF)                              │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    重排序层                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Rerank模型精排 → 取TOP-K → 过滤低分结果              │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    上下文优化层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ 提示词压缩   │  │ 冲突检测    │  │ 时效性标注          │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    大模型生成层                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 严格Prompt约束 + 来源引用 + 置信度标注               │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    后处理验证层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ 事实核查    │  │ 来源验证    │  │ 幻觉检测            │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                      最终回答                                │
│        答案 + 来源 + 置信度 + (冲突/时效提示)               │
└─────────────────────────────────────────────────────────────┘
```

---

## 五、实施优先级

| 优先级 | 优化项 | 实现难度 | 效果提升 | 说明 |
|--------|--------|----------|----------|------|
| 🔴 P0 | Prompt约束 | 低 | 显著 | 改动最小，效果明显 |
| 🔴 P0 | Rerank重排序 | 中 | 显著 | 提升检索精度 |
| 🟡 P1 | Query改写 | 低 | 中等 | 解决口语化问题 |
| 🟡 P1 | 混合检索 | 中 | 中等 | 向量+关键词互补 |
| 🟡 P1 | 置信度标注 | 低 | 中等 | 让用户知道答案可靠程度 |
| 🟢 P2 | HyDE | 中 | 中等 | 特定场景效果好 |
| 🟢 P2 | 冲突检测 | 中 | 中等 | 提升可信度 |
| 🟢 P2 | 语义切片 | 中 | 中等 | 优化知识库质量 |
| 🔵 P3 | 迭代检索 | 高 | 针对性强 | 解决多跳问题 |
| 🔵 P3 | GraphRAG | 高 | 针对性强 | 复杂关联查询 |

---

## 六、评估指标

优化后可通过以下指标评估效果：

| 指标 | 说明 | 计算方式 |
|------|------|----------|
| **准确率** | 回答正确的比例 | 正确回答数 / 总问题数 |
| **召回率** | 相关内容被检索到的比例 | 召回相关片段数 / 总相关片段数 |
| **幻觉率** | 编造信息的比例 | 包含幻觉的回答数 / 总回答数 |
| **来源引用率** | 正确引用来源的比例 | 正确引用数 / 应引用数 |
| **用户满意度** | 主观评价 | 问卷/反馈 |

---

## 七、参考资料

- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)
- [HyDE: Precise Zero-Shot Dense Retrieval](https://arxiv.org/abs/2212.10496)
- [BGE Reranker Models](https://huggingface.co/BAAI/bge-reranker-base)
- [LLMLingua: Prompt Compression](https://github.com/microsoft/LLMLingua)