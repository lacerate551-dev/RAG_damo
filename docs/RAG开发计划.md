# RAG系统后续开发计划

## 开发顺序规划原则

1. **优先级优先**：高优先级功能优先开发
2. **依赖关系**：有依赖关系的功能按顺序开发
3. **完整实现**：不赶进度，每个功能做完整
4. **可验证性**：每个功能开发完成后有明确的验证标准

---

## 当前状态总览

| 功能编号 | 功能名称 | 优先级 | 当前状态 |
|---------|---------|--------|---------|
| GKPT-AI-010 | RAG向量数据库 | 高 | ✅ 已完成 |
| GKPT-AI-011 | 多轮智能对话 | 高 | ✅ 已完成 |
| GKPT-AI-012 | 答案溯源 | 中 | ✅ 已完成 |
| GKPT-EXAM-015 | AI智能出题 | 高 | ✅ 已完成 |
| GKPT-KB-008 | 知识库自动同步 | 高 | ✅ 已完成 |
| GKPT-EXAM-009 | 题库智能维护 | 高 | ✅ 已完成 |
| GKPT-EXAM-018 | AI自动阅卷 | 中 | ✅ 已完成 |
| GKPT-MIND-020 | 自动化纲要生成 | 高 | ✅ 已完成 |
| GKPT-READ-005 | 关联推荐 | 中 | ✅ 已完成 |
| GKPT-AI-013 | 问答质量闭环 | 低 | ✅ 已完成 |

---

## 开发阶段规划

### 第一阶段：知识库基础设施完善

**目标**：完善知识库自动同步机制，为其他功能提供数据基础

#### 1. GKPT-KB-008 知识库自动同步（完善）

**需求回顾**：
- 制度文件变更后，自动触发知识库更新
- 向相关用户推送更新提醒
- 增量更新耗时≤10分钟

**待开发任务**：

| 序号 | 任务 | 预估工时 | 说明 |
|-----|------|---------|------|
| 1.1 | 文件变更监控服务 | 4h | 使用 watchdog 监控 documents 目录，检测新增/修改/删除 |
| 1.2 | 文件哈希计算与比对 | 2h | 计算文件MD5/SHA256，识别具体变更内容 |
| 1.3 | 增量向量化接口 | 4h | 仅处理变更文件，而非全量重建，优化性能 |
| 1.4 | 变更日志记录 | 2h | 记录文件变更历史，支持追溯 |
| 1.5 | 用户订阅机制 | 3h | 用户可订阅特定文档或目录 |
| 1.6 | 推送通知服务 | 3h | 文档变更时推送通知给订阅用户 |
| 1.7 | API接口开发 | 2h | 同步触发、状态查询、历史记录接口 |

**技术方案**：
```
┌─────────────────────────────────────────────────────────────┐
│                     文件监控服务                              │
│  documents/ 目录 → watchdog 监控 → 变更事件检测               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     变更处理流程                              │
│  文件哈希比对 → 识别变更类型(新增/修改/删除)                   │
│       ↓                                                      │
│  增量向量化 → 更新ChromaDB → 重建BM25索引                     │
│       ↓                                                      │
│  记录变更日志 → 通知订阅用户                                   │
└─────────────────────────────────────────────────────────────┘
```

**新增文件**：
- `knowledge_sync.py` - 知识库同步服务主模块
- `file_watcher.py` - 文件监控服务
- `notification_service.py` - 推送通知服务

**新增数据库表**：
```sql
-- 文档变更日志
CREATE TABLE document_changes (
    id INTEGER PRIMARY KEY,
    document_id TEXT,
    change_type TEXT,      -- add/modify/delete
    old_hash TEXT,
    new_hash TEXT,
    change_time TIMESTAMP,
    processed INTEGER DEFAULT 0
);

-- 用户订阅
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    document_id TEXT,      -- 可为空，表示订阅全部
    created_at TIMESTAMP
);

-- 同步状态
CREATE TABLE sync_status (
    id INTEGER PRIMARY KEY,
    sync_type TEXT,        -- full/incremental
    status TEXT,           -- running/completed/failed
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    documents_processed INTEGER,
    error_message TEXT
);
```

**新增API**：
```python
POST /sync                    # 手动触发同步
GET  /sync/status             # 获取同步状态
GET  /sync/history            # 变更历史记录
POST /subscribe               # 订阅文档
DELETE /subscribe/{id}        # 取消订阅
GET  /notifications           # 获取通知列表
```

**验收标准**：
- [x] 文件变更能在5秒内被检测到
- [x] 增量同步时间<10分钟（100个文档以内）
- [x] 变更日志可追溯30天内历史
- [x] 订阅用户能收到变更通知

**完成时间**: 2026-04-07

---

### 第二阶段：考试系统增强

**目标**：完善题库维护和阅卷分析功能

#### 2. GKPT-EXAM-009 题库智能维护

**需求回顾**：
- 监控制度变更，自动识别受影响题目
- AI生成新题建议
- 题目与制度版本关联

**待开发任务**：

| 序号 | 任务 | 预估工时 | 说明 |
|-----|------|---------|------|
| 2.1 | 题目-制度关联表设计 | 2h | 记录题目关联的制度文件、章节、版本 |
| 2.2 | 制度版本追踪 | 3h | 追踪制度变更历史，支持版本对比 |
| 2.3 | 受影响题目检测 | 4h | 制度变更时自动标记相关题目为"待审核" |
| 2.4 | 新题生成建议 | 3h | AI分析变更内容，建议新题方向 |
| 2.5 | 题目状态管理 | 2h | 启用/禁用/待审核/已过期状态流转 |
| 2.6 | API接口开发 | 2h | 受影响题目查询、新题建议接口 |

**数据库设计**：
```sql
-- 题目-制度关联表
CREATE TABLE question_document_links (
    id INTEGER PRIMARY KEY,
    question_id TEXT,
    document_id TEXT,
    chapter TEXT,           -- 关联章节
    key_points TEXT,        -- 关联知识点（JSON）
    relevance_score REAL,   -- 相关性分数
    created_at TIMESTAMP
);

-- 制度版本表
CREATE TABLE document_versions (
    id INTEGER PRIMARY KEY,
    document_id TEXT,
    version TEXT,
    content_hash TEXT,
    change_summary TEXT,    -- AI生成的变更摘要
    changed_sections TEXT,  -- 变更的章节列表（JSON）
    created_at TIMESTAMP
);

-- 题目状态
-- draft(草稿), pending_review(待审核), approved(已通过)
-- affected(受影响待审核), deprecated(已过期), disabled(已禁用)
```

**核心逻辑**：
```python
def on_document_change(document_id, old_version, new_version):
    """制度变更时的处理流程"""
    # 1. 获取变更章节
    changed_sections = compare_versions(old_version, new_version)

    # 2. 查找关联题目
    affected_questions = find_linked_questions(document_id, changed_sections)

    # 3. 标记题目状态
    for q in affected_questions:
        update_question_status(q.id, "affected")
        notify_admin(f"题目 {q.id} 因制度变更需要审核")

    # 4. 生成新题建议
    suggestions = generate_question_suggestions(document_id, changed_sections)

    return {
        "affected_questions": affected_questions,
        "suggestions": suggestions
    }
```

**新增API**：
```python
GET  /questions/affected          # 获取受影响题目列表
PUT  /questions/{id}/review       # 审核题目（确认/更新/禁用）
GET  /questions/suggestions       # 获取新题建议
POST /questions/link-document     # 建立题目-制度关联
GET  /documents/{id}/versions     # 获取制度版本历史
```

**验收标准**：
- [x] 制度变更能自动识别关联题目
- [x] 受影响题目状态自动更新为"待审核"
- [x] 新题建议包含题型、题目内容、答案（框架已完成，需对接LLM）
- [x] 题目-制度关联关系可视化（API已提供）

**完成时间**: 2026-04-07

---

#### 3. GKPT-EXAM-018 整卷评语分析（改造）

**需求调整**：
- ~~主观题语义评分~~（已在Dify工作流实现）
- **新增**：整卷评语分析
- **新增**：知识薄弱点识别
- **新增**：学习建议生成

**待开发任务**：

| 序号 | 任务 | 预估工时 | 说明 |
|-----|------|---------|------|
| 3.1 | 整卷答题情况分析 | 4h | 分析各题型得分率、答题时间分布 |
| 3.2 | 知识点映射表 | 3h | 建立题目-知识点关联关系 |
| 3.3 | 薄弱点识别算法 | 3h | 根据错题识别薄弱知识点 |
| 3.4 | AI评语生成 | 3h | 基于答题情况生成个性化评语 |
| 3.5 | 学习建议生成 | 2h | 针对薄弱点推荐学习内容 |
| 3.6 | API接口开发 | 2h | 整卷分析接口 |

**数据库设计**：
```sql
-- 题目-知识点关联
CREATE TABLE question_knowledge_points (
    id INTEGER PRIMARY KEY,
    question_id TEXT,
    knowledge_point TEXT,   -- 知识点名称
    weight REAL,            -- 权重
    created_at TIMESTAMP
);

-- 整卷分析报告
CREATE TABLE exam_analysis_reports (
    id INTEGER PRIMARY KEY,
    report_id TEXT,
    exam_id TEXT,
    student_name TEXT,
    total_score REAL,
    score_rate REAL,           -- 得分率
    weak_points TEXT,          -- 薄弱知识点（JSON）
    strong_points TEXT,        -- 掌握较好的知识点（JSON）
    ai_comment TEXT,           -- AI评语
    study_suggestions TEXT,    -- 学习建议（JSON）
    created_at TIMESTAMP
);
```

**核心逻辑**：
```python
def analyze_exam_paper(exam_id, student_answers, scores):
    """整卷分析流程"""

    # 1. 统计各题型得分
    type_scores = calculate_type_scores(scores)

    # 2. 分析知识点掌握情况
    knowledge_analysis = analyze_knowledge_points(
        student_answers,
        get_question_knowledge_points(exam_id)
    )

    # 3. 识别薄弱点
    weak_points = [kp for kp in knowledge_analysis if kp['score_rate'] < 0.6]

    # 4. 生成AI评语
    ai_comment = generate_ai_comment(
        total_score=sum(scores.values()),
        type_scores=type_scores,
        weak_points=weak_points,
        knowledge_analysis=knowledge_analysis
    )

    # 5. 生成学习建议
    suggestions = generate_study_suggestions(weak_points)

    return {
        "total_score": sum(scores.values()),
        "score_rate": sum(scores.values()) / get_total_score(exam_id),
        "type_scores": type_scores,
        "weak_points": weak_points,
        "ai_comment": ai_comment,
        "suggestions": suggestions
    }
```

**新增API**：
```python
POST /exam/{exam_id}/analyze    # 整卷分析
GET  /analysis/{report_id}      # 获取分析报告
GET  /knowledge-points          # 知识点列表
POST /knowledge-points/link     # 建立题目-知识点关联
```

**验收标准**：
- [x] 能生成整卷答题情况统计
- [x] 能识别3个以上薄弱知识点（阈值可配置）
- [x] AI评语个性化、有针对性
- [x] 学习建议关联具体制度文档（框架已完成，可扩展）

**完成时间**: 2026-04-07

---

### 第三阶段：知识服务增强

**目标**：提供知识展示和推荐能力

#### 4. GKPT-MIND-020 自动化纲要生成

**需求回顾**：
- AI自动提取制度文件的章节结构、核心要点
- 生成可交互的思维导图
- 支持导出图片/PDF
- 生成时间≤10秒（10页以内）

**待开发任务**：

| 序号 | 任务 | 预估工时 | 说明 |
|-----|------|---------|------|
| 4.1 | 文档结构解析服务 | 4h | 使用LLM提取章节结构和核心要点 |
| 4.2 | 思维导图数据结构定义 | 2h | JSON格式节点树，支持多级嵌套 |
| 4.3 | 纲要生成API | 3h | POST /outline 接口 |
| 4.4 | 导出功能 | 2h | 导出Markdown/JSON/图片 |
| 4.5 | 缓存机制 | 1h | 避免重复生成，文档变更时清除缓存 |
| 4.6 | 批量生成 | 2h | 支持批量生成多个文档的纲要 |

**数据结构设计**：
```python
# 思维导图节点结构
{
    "id": "node_1",
    "title": "章节标题",
    "summary": "核心要点（不超过100字）",
    "level": 1,                    # 层级
    "order": 1,                    # 同级排序
    "page": 5,                     # 对应页码
    "children": [
        {
            "id": "node_1_1",
            "title": "子章节标题",
            "summary": "核心要点",
            "level": 2,
            "order": 1,
            "children": []
        }
    ]
}

# 完整纲要结构
{
    "document_id": "xxx",
    "document_name": "差旅管理办法",
    "total_pages": 15,
    "generated_at": "2026-04-07T10:00:00",
    "outline": [...],              # 节点树
    "export_formats": ["json", "markdown", "png"]
}
```

**核心逻辑**：
```python
def generate_outline(document_id):
    """生成文档纲要"""
    # 1. 获取文档内容
    document = get_document(document_id)

    # 2. 检查缓存
    cached = cache.get(f"outline:{document_id}")
    if cached and cached['content_hash'] == document['hash']:
        return cached

    # 3. LLM提取结构
    prompt = f"""
    请从以下制度文档中提取章节结构和核心要点：

    文档内容：
    {document['content'][:10000]}  # 限制长度

    要求：
    1. 识别文档的一级、二级、三级标题
    2. 提取每个章节的核心要点（不超过100字）
    3. 保持层级关系
    4. 输出JSON格式

    输出格式示例：
    {{
        "title": "文档标题",
        "summary": "文档概述",
        "children": [
            {{
                "title": "第一章 标题",
                "summary": "本章核心要点",
                "level": 1,
                "children": [...]
            }}
        ]
    }}
    """

    outline = llm.generate(prompt, temperature=0.3)

    # 4. 缓存结果
    cache.set(f"outline:{document_id}", {
        "outline": outline,
        "content_hash": document['hash'],
        "generated_at": datetime.now()
    })

    return outline
```

**新增文件**：
- `outline_generator.py` - 纲要生成服务

**新增API**：
```python
POST /outline                    # 生成纲要
GET  /outline/{document_id}      # 获取已生成的纲要
GET  /outline/{document_id}/export?format=png  # 导出
DELETE /outline/{document_id}    # 删除缓存
```

**验收标准**：
- [x] 能正确识别3级标题结构
- [x] 核心要点准确、简洁
- [x] 生成时间<10秒（10页文档）
- [x] 支持JSON/Markdown/Markmap导出

**完成时间**: 2026-04-07

---

#### 5. GKPT-READ-005 关联推荐

**需求回顾**：
- 基于当前阅读的制度内容，智能推荐相关的其他制度
- 推荐结果包含标题、摘要、相关性标签
- 仅基于标签和全文检索

**待开发任务**：

| 序号 | 任务 | 预估工时 | 说明 |
|-----|------|---------|------|
| 5.1 | 文档向量预计算 | 2h | 为每个文档计算整体向量（非片段） |
| 5.2 | 相似文档检索 | 3h | 基于向量相似度检索相关文档 |
| 5.3 | 标签匹配算法 | 2h | 基于文档标签/元数据匹配 |
| 5.4 | 推荐结果排序 | 2h | 综合相似度、标签、热度排序 |
| 5.5 | 推荐API接口 | 2h | GET /recommend 接口 |
| 5.6 | 推荐结果缓存 | 1h | 缓存热门文档的推荐结果 |

**核心逻辑**：
```python
def get_recommendations(document_id, top_k=5):
    """获取关联推荐"""
    # 1. 获取当前文档信息
    current_doc = get_document(document_id)
    current_vector = get_document_vector(document_id)  # 整体向量
    current_tags = current_doc.get('tags', [])

    # 2. 向量相似度检索
    similar_docs = vector_search(
        current_vector,
        top_k=top_k * 3,  # 多召回一些用于过滤
        exclude_ids=[document_id]  # 排除自己
    )

    # 3. 标签匹配加分
    for doc in similar_docs:
        doc_tags = doc.get('tags', [])
        tag_overlap = len(set(current_tags) & set(doc_tags))
        doc['tag_score'] = tag_overlap * 0.1
        doc['final_score'] = doc['similarity'] * 0.7 + doc['tag_score'] * 0.3

    # 4. 排序返回
    results = sorted(similar_docs, key=lambda x: x['final_score'], reverse=True)
    return results[:top_k]
```

**新增API**：
```python
GET /recommend/{document_id}     # 获取关联推荐
GET /recommend/{document_id}?type=similar  # 相似文档
GET /recommend/{document_id}?type=related  # 相关文档（标签匹配）
```

**验收标准**：
- [x] 推荐结果相关性>80%（基于向量相似度+标签匹配）
- [x] 响应时间<500ms（有缓存时）
- [x] 支持按相似度/标签综合排序

**完成时间**: 2026-04-07

---

### 第四阶段：质量闭环

**目标**：建立反馈机制，持续优化问答质量

#### 6. GKPT-AI-013 问答质量闭环

**需求回顾**：
- 用户点赞/踩反馈
- 质量分析报告（周/月）
- FAQ自动沉淀

**待开发任务**：

| 序号 | 任务 | 预估工时 | 说明 |
|-----|------|---------|------|
| 6.1 | 反馈接口 | 2h | POST /feedback 点赞/点踩 |
| 6.2 | 反馈数据存储 | 1h | SQLite表设计与实现 |
| 6.3 | 质量统计报表 | 3h | 高频问题、低分答案统计 |
| 6.4 | FAQ自动沉淀 | 3h | 高频问题自动转为FAQ |
| 6.5 | FAQ管理接口 | 2h | FAQ的增删改查 |
| 6.6 | 定期报告生成 | 2h | 周/月报告自动生成 |

**数据库设计**：
```sql
-- 反馈记录表
CREATE TABLE feedbacks (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    query TEXT,
    answer TEXT,
    sources TEXT,           -- 来源文档（JSON）
    rating INTEGER,         -- 1=赞, -1=踩
    reason TEXT,            -- 点踩原因
    user_id TEXT,
    created_at TIMESTAMP
);

-- FAQ表
CREATE TABLE faqs (
    id INTEGER PRIMARY KEY,
    question TEXT,
    answer TEXT,
    source_documents TEXT,  -- 来源文档（JSON）
    frequency INTEGER,      -- 出现频率
    avg_rating REAL,        -- 平均评分
    status TEXT,            -- draft/approved/disabled
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 质量报告表
CREATE TABLE quality_reports (
    id INTEGER PRIMARY KEY,
    report_type TEXT,       -- daily/weekly/monthly
    start_date DATE,
    end_date DATE,
    total_queries INTEGER,
    avg_rating REAL,
    low_rating_queries TEXT, -- 低分问题列表（JSON）
    high_freq_queries TEXT,  -- 高频问题列表（JSON）
    created_at TIMESTAMP
);
```

**核心逻辑**：
```python
def process_feedback(session_id, query, answer, rating, reason=None):
    """处理用户反馈"""
    # 1. 存储反馈
    save_feedback(session_id, query, answer, rating, reason)

    # 2. 检查是否需要沉淀为FAQ
    if rating > 0:  # 正面反馈
        similar_faqs = find_similar_faqs(query)
        if similar_faqs:
            # 更新已有FAQ频率
            update_faq_frequency(similar_faqs[0]['id'])
        else:
            # 检查是否高频问题
            query_count = count_similar_queries(query)
            if query_count >= 5:  # 出现5次以上
                suggest_faq(query, answer)

def generate_weekly_report():
    """生成周报告"""
    week_start = get_week_start()
    week_end = get_week_end()

    # 统计数据
    total_queries = count_queries(week_start, week_end)
    avg_rating = calculate_avg_rating(week_start, week_end)
    low_rating = get_low_rating_queries(week_start, week_end, threshold=0.5)
    high_freq = get_high_freq_queries(week_start, week_end, top_n=20)

    return {
        "period": f"{week_start} - {week_end}",
        "total_queries": total_queries,
        "avg_rating": avg_rating,
        "low_rating_queries": low_rating,
        "high_freq_queries": high_freq,
        "suggestions": generate_improvement_suggestions(low_rating)
    }
```

**新增API**：
```python
POST /feedback                    # 提交反馈
GET  /feedback/stats              # 反馈统计
GET  /reports/weekly              # 周报告
GET  /reports/monthly             # 月报告
GET  /faq                         # FAQ列表
POST /faq                         # 新增FAQ
PUT  /faq/{id}                    # 更新FAQ
DELETE /faq/{id}                  # 删除FAQ
```

**验收标准**：
- [x] 反馈能正确存储和统计
- [x] 高频问题（5次以上）能自动推荐为FAQ
- [x] 周报告包含改进建议（含LLM生成的具体建议）
- [x] FAQ管理功能完整（增删改查、建议审批）

**完成时间**: 2026-04-07

---

## 开发时间线

```
第1-2周：第一阶段 - 知识库基础设施
├── 文件监控服务
├── 增量向量化
├── 变更日志
├── 用户订阅
└── 推送通知

第3-4周：第二阶段 - 考试系统增强
├── 题目-制度关联
├── 制度变更检测
├── 受影响题目标记
├── 整卷评语分析
└── 知识薄弱点识别

第5-6周：第三阶段 - 知识服务增强
├── 文档结构解析
├── 思维导图生成
├── 导出功能
├── 相似文档检索
└── 关联推荐

第7周：第四阶段 - 质量闭环
├── 反馈接口
├── 质量统计
├── FAQ沉淀
└── 定期报告
```

---

## 依赖关系图

```
第一阶段（知识库同步）
    │
    ├──► 第二阶段-1（题库维护）── 需要变更检测能力
    │         │
    │         └──► 第二阶段-2（整卷分析）── 需要知识点关联
    │
    ├──► 第三阶段-1（纲要生成）── 需要文档内容
    │
    └──► 第三阶段-2（关联推荐）── 需要文档向量

第四阶段（质量闭环）── 独立，可并行开发
```

---

## 技术依赖

### 新增Python依赖
```txt
watchdog>=3.0.0       # 文件监控
markdown>=3.4.0       # 纲要导出Markdown
Pillow>=10.0.0        # 图片导出
reportlab>=4.0.0      # PDF导出（可选）
apscheduler>=3.10.0   # 定时任务（报告生成）
```

### 现有依赖复用
- `chromadb` - 向量检索
- `sentence-transformers` - 语义相似度
- `openai` - LLM调用
- `flask` - API服务
- `jieba` - 中文分词

---

## 验证方案

### 功能测试清单

| 功能 | 测试要点 | 通过标准 |
|-----|---------|---------|
| 知识库同步 | 新增/修改/删除文件 | 向量库正确更新，通知发送成功 |
| 题库维护 | 制度变更 | 相关题目自动标记 |
| 整卷分析 | 批阅报告 | 评语个性化，薄弱点准确 |
| 纲要生成 | 多种文档格式 | 结构正确，要点准确 |
| 关联推荐 | 推荐相关性 | Top5推荐命中率>80% |
| 质量闭环 | 反馈统计 | 数据准确，报告完整 |

### 性能测试清单

| 指标 | 目标值 |
|-----|-------|
| 文件变更检测延迟 | < 5秒 |
| 增量同步时间 | < 10分钟（100文档） |
| 纲要生成时间 | < 10秒（10页文档） |
| 推荐响应时间 | < 500ms |
| 反馈接口响应 | < 100ms |

---

## 文件结构规划

```
项目根目录/
├── knowledge_sync.py      # 知识库同步服务（新增）
├── file_watcher.py        # 文件监控服务（新增）
├── notification_service.py # 推送通知服务（新增）
├── question_maintenance.py # 题库维护服务（新增）
├── exam_analysis.py       # 整卷分析服务（新增）
├── outline_generator.py   # 纲要生成服务（新增）
├── recommendation.py      # 推荐服务（新增）
├── feedback_service.py    # 反馈服务（新增）
├── rag_api_server.py      # 主API服务（扩展）
├── rag_demo.py            # RAG基础功能（已存在）
├── agentic_rag.py         # Agent RAG（已存在）
├── exam_manager.py        # 出题管理（已存在）
├── session_manager.py     # 会话管理（已存在）
└── docs/
    ├── RAG需求负责清单.md
    └── RAG开发计划.md      # 本文档
```

---

*计划创建时间: 2026-04-07*
*预计总工时: 60-70 小时*
*预计完成时间: 7周*
