# RAG 服务 API 接口规范

> 本文档供后端开发人员参考，用于对接 RAG 知识库服务。
> 
> **文档版本**: v3.1  
> **最后更新**: 2026-04-26  
> **维护者**: RAG服务开发组

---

## 一、服务概述

### 1.1 职责边界

| 职责 | 后端负责 | RAG服务负责 |
|------|----------|-------------|
| **用户认证** | JWT/Session 验证 | - |
| **权限判断** | 判断用户可访问的知识库 | - |
| **会话管理** | 创建/删除会话，存储消息 | - |
| **知识库问答** | - | 检索 + 生成回答 |
| **向量检索** | - | 向量 + BM25 混合检索 |
| **文档处理** | - | 上传、解析、切片、向量化 |
| **反馈系统** | - | 收集反馈、FAQ 管理 |

### 1.2 数据流

```
┌─────────┐    ┌─────────┐    ┌─────────┐
│  前端   │───▶│  后端   │───▶│   RAG   │
└─────────┘    └─────────┘    └─────────┘
                    │               │
                    ▼               ▼
              ┌──────────┐   ┌──────────┐
              │ 权限判断 │   │ 向量检索 │
              │ 会话管理 │   │ 生成回答 │
              └──────────┘   └──────────┘
```

### 1.3 服务端口

- **默认端口**: 5001
- **启动命令**: `python main.py`

---

## 二、认证方式

### 2.1 生产模式（APP_ENV=prod）

后端调用 RAG 服务时，**不需要传认证 Header**。权限由后端通过 `collections` 参数控制。

```http
POST http://localhost:5001/rag
Content-Type: application/json

{
  "message": "出差补助标准是什么？",
  "collections": ["public_kb", "dept_finance"],
  "chat_history": []
}
```

### 2.2 开发模式（APP_ENV=dev）

支持模拟用户测试，可通过 Header 传递用户信息：

```http
POST http://localhost:5001/rag
Content-Type: application/json
X-User-ID: admin001
X-User-Role: admin
X-User-Department: 技术部

{
  "message": "问题",
  "collections": ["public_kb"],
  "chat_history": []
}
```

**模拟用户列表**：

| X-User-ID | X-User-Role | 说明 |
|-----------|-------------|------|
| admin001 | admin | 管理员 |
| manager001 | manager | 部门管理员 |
| user001 | user | 普通用户 |

### 2.3 环境配置

```bash
# 生产环境
APP_ENV=prod
DASHSCOPE_API_KEY=your-api-key-here

# 开发环境（默认）
APP_ENV=dev
```

---

## 三、核心接口

### 3.1 健康检查

```
GET /health
```

**认证**: 不需要

**响应**:
```json
{
  "status": "ok",
  "knowledge_base": "多向量库模式 (按集合提供服务)",
  "bm25_index": "动态按需加载",
  "mode": "Agentic RAG"
}
```

### 3.2 知识库问答（核心接口）

```
POST /rag
```

**认证**: 不需要（生产模式）

**请求体**:
```json
{
  "message": "用户问题",
  "collections": ["public_kb", "dept_finance"],
  "chat_history": [
    {"role": "user", "content": "历史问题"},
    {"role": "assistant", "content": "历史回答"}
  ]
}
```

**参数说明**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `message` | string | ✅ | 用户问题 |
| `collections` | string[] | ✅ | 用户有权限的知识库列表，由后端判断后传入 |
| `chat_history` | array | ✅ | 对话历史（生产环境必须传入） |

**响应**: SSE 流式返回

```
Content-Type: text/event-stream

data: {"type": "start", "message": "正在检索知识库..."}

data: {"type": "sources", "sources": [{"source": "doc.pdf", "page": 1, "page_range": "1", "section": "", "chunk_type": "text", "score": 0.95}]}

data: {"type": "chunk", "content": "根"}

data: {"type": "chunk", "content": "据"}

...

data: {"type": "finish", "answer": "完整答案...", "mode": "rag", "sources": [...], "images": [], "tables": [], "duration_ms": 1500}
```

**SSE 事件类型**:

| 事件类型 | 说明 |
|---------|------|
| `start` | 开始处理 |
| `sources` | 检索到的来源 |
| `chunk` | 每个 token（打字机效果） |
| `finish` | 完整响应对象（**必须消费**） |
| `error` | 错误事件 |

**finish 事件结构**:
```json
{
  "type": "finish",
  "answer": "完整答案文本",
  "mode": "rag",
  "sources": [
    {
      "source": "文档名.pdf",
      "page": 5,
      "page_end": 8,
      "page_range": "5-8",
      "section": "1. Introduction",
      "chunk_type": "text",
      "score": 0.856
    }
  ],
  "images": [],
  "tables": [],
  "sections": ["章节路径"],
  "duration_ms": 1500
}
```

**后端消费示例（Python）**:
```python
import requests
import json

def call_rag_stream(message, collections, history=None):
    response = requests.post(
        'http://localhost:5001/rag',
        json={
            'message': message,
            'collections': collections,
            'chat_history': history or []
        },
        stream=True
    )

    full_answer = ''
    sources = []

    for line in response.iter_lines():
        if not line:
            continue

        line = line.decode('utf-8')
        if line.startswith('data: '):
            event = json.loads(line[6:])

            if event['type'] == 'sources':
                sources = event['sources']
            elif event['type'] == 'chunk':
                full_answer += event['content']
            elif event['type'] == 'finish':
                full_answer = event['answer']
                sources = event['sources']
                break
            elif event['type'] == 'error':
                raise Exception(event['message'])

    return full_answer, sources

# 使用
answer, sources = call_rag_stream('出差补助标准是什么？', ['public_kb'])
```

### 3.3 普通聊天

```
POST /chat
```

**请求体**:
```json
{
  "message": "用户消息",
  "chat_history": []
}
```

**响应**: SSE 流式返回（同 /rag）

### 3.4 混合检索

```
POST /search
```

**请求体**:
```json
{
  "message": "检索关键词",
  "collections": ["public_kb"],
  "chat_history": []
}
```

**响应**:
```json
{
  "contexts": ["文档片段1", "文档片段2"],
  "metadatas": [
    {"source": "doc1.pdf", "page": 1},
    {"source": "doc2.pdf", "page": 5}
  ],
  "scores": [0.95, 0.87]
}
```

---

## 四、知识库管理接口

### 4.1 获取向量库列表

```
GET /collections
```

**响应**:
```json
{
  "collections": [
    {
      "name": "public_kb",
      "display_name": "公开知识库",
      "document_count": 137,
      "department": "",
      "description": "所有人可访问"
    }
  ],
  "total": 1
}
```

### 4.2 创建向量库

```
POST /collections
```

**请求体**:
```json
{
  "name": "dept_finance",
  "display_name": "财务部知识库",
  "department": "finance",
  "description": "财务部专用知识库"
}
```

### 4.3 删除向量库

```
DELETE /collections/<name>
```

### 4.4 获取向量库文档列表

```
GET /collections/<kb_name>/documents
```

**响应**:
```json
{
  "collection": "public_kb",
  "documents": [
    {"source": "文档名.pdf", "chunks": 30}
  ],
  "total": 3
}
```

### 4.5 知识库路由测试

```
POST /kb/route
```

**请求体**:
```json
{
  "query": "财务部报销流程"
}
```

**响应**:
```json
{
  "target_collections": ["dept_finance", "public_kb"],
  "routing_reason": "检测到部门关键词"
}
```

---

## 五、文档管理接口

### 5.1 上传文档

```
POST /documents/upload
Content-Type: multipart/form-data
```

**表单参数**:
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `file` | file | ✅ | 文件 |
| `collection` | string | ✅ | 目标向量库名称 |

**响应**:
```json
{
  "success": true,
  "message": "文件上传成功，已添加到向量库",
  "file": {
    "filename": "document.pdf",
    "collection": "public_kb",
    "path": "public/document.pdf",
    "size": 1024000
  },
  "chunk_count": 15
}
```

### 5.2 批量上传

```
POST /documents/batch-upload
Content-Type: multipart/form-data
```

**表单参数**:
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `files` | file[] | ✅ | 文件列表 |
| `collection` | string | ✅ | 目标向量库名称 |

### 5.3 文档列表

```
GET /documents/list
```

**响应**:
```json
{
  "documents": [
    {
      "collection": "public_kb",
      "filename": "文档名.pdf",
      "path": "public_kb/文档名.pdf",
      "size": 1024000,
      "last_modified": "2026-04-26T10:00:00"
    }
  ]
}
```

### 5.4 删除文档

```
DELETE /documents/<path>
```

### 5.5 查看文档切片

```
GET /documents/<path>/chunks
```

### 5.6 文档状态

```
GET /documents/<path>/status
```

---

## 六、切片管理接口

### 6.1 新增切片

```
POST /chunks
```

**请求体**:
```json
{
  "collection": "public_kb",
  "document_id": "doc_001",
  "content": "切片内容",
  "metadata": {"page": 1, "section": "第一章"}
}
```

### 6.2 修改切片

```
PUT /chunks/<chunk_id>
```

### 6.3 删除切片

```
DELETE /chunks/<chunk_id>
```

---

## 七、同步服务接口

### 7.1 同步状态

```
GET /sync/status
```

**响应**:
```json
{
  "enabled": true,
  "monitoring": false,
  "last_sync": null,
  "documents_tracked": 0
}
```

### 7.2 触发同步

```
POST /sync
```

**请求体**（可选）:
```json
{
  "collection": "public_kb",
  "full_sync": false
}
```

### 7.3 同步历史

```
GET /sync/history?limit=20
```

### 7.4 变更日志

```
GET /sync/changes?limit=50
```

### 7.5 启动/停止监控

```
POST /sync/start
POST /sync/stop
```

---

## 八、图片服务接口

### 8.1 获取图片

```
GET /images/<image_id>
```

**响应**: 图片二进制数据

### 8.2 图片信息

```
GET /images/<image_id>/info
```

### 8.3 图片列表

```
GET /images/list?limit=20
```

**响应**:
```json
{
  "images": [
    {
      "image_id": "abc123",
      "size_bytes": 56932,
      "url": "/images/abc123"
    }
  ],
  "total": 11
}
```

### 8.4 图片统计

```
GET /images/stats
```

---

## 九、反馈系统接口

### 9.1 提交反馈

```
POST /feedback
```

**请求体**:
```json
{
  "session_id": "xxx",
  "query": "问题内容",
  "answer": "回答内容",
  "rating": 1,
  "sources": ["doc.pdf"],
  "reason": "回答准确"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `rating` | int | `1`=赞, `-1`=踩 |

### 9.2 反馈统计

```
GET /feedback/stats
```

**响应**:
```json
{
  "success": true,
  "stats": {
    "total_feedback": 4,
    "positive_count": 4,
    "negative_count": 0,
    "satisfaction_rate": 100.0
  }
}
```

### 9.3 反馈列表

```
GET /feedback/list
```

### 9.4 周报/月报

```
GET /reports/weekly
GET /reports/monthly
```

---

## 十、FAQ 管理接口

### 10.1 FAQ 列表

```
GET /faq
```

**响应**:
```json
{
  "faqs": [
    {
      "id": 1,
      "question": "问题",
      "answer": "答案",
      "frequency": 5,
      "status": "approved"
    }
  ]
}
```

### 10.2 新增 FAQ

```
POST /faq
```

**请求体**:
```json
{
  "question": "问题",
  "answer": "答案",
  "source_documents": ["doc.pdf"]
}
```

### 10.3 更新/删除 FAQ

```
PUT /faq/<faq_id>
DELETE /faq/<faq_id>
```

### 10.4 FAQ 建议列表

```
GET /faq/suggestions
```

### 10.5 批准/拒绝建议

```
POST /faq/suggestions/<id>/approve
POST /faq/suggestions/<id>/reject
```

---

## 十一、出题系统接口

### 11.1 健康检查

```
GET /exam/health
```

**响应**:
```json
{
  "service": "exam-api",
  "status": "ok",
  "version": "2.0"
}
```

### 11.2 生成题目

```
POST /exam/generate
```

**请求体**:
```json
{
  "file_path": "public/考勤制度.docx",
  "collection": "public_kb",
  "question_types": {
    "single_choice": 3,
    "multiple_choice": 2,
    "true_false": 2,
    "fill_blank": 2,
    "subjective": 1
  },
  "difficulty": 3,
  "request_id": "可选，幂等性支持"
}
```

**响应**:
```json
{
  "success": true,
  "total": 10,
  "questions": [
    {
      "question_type": "single_choice",
      "difficulty": 3,
      "content": {
        "stem": "题干内容",
        "data": {
          "options": [
            {"key": "A", "content": "选项A"},
            {"key": "B", "content": "选项B"}
          ]
        },
        "answer": "B",
        "explanation": "解析"
      },
      "source_trace": {
        "document_name": "考勤制度.docx",
        "page_numbers": [5]
      }
    }
  ]
}
```

### 11.3 批改答案

```
POST /exam/grade
```

**请求体**:
```json
{
  "answers": [
    {
      "question_id": "q001",
      "question_type": "single_choice",
      "question_content": {
        "stem": "题干",
        "data": {"options": [...]},
        "answer": "B"
      },
      "student_answer": "A",
      "max_score": 2.0
    }
  ]
}
```

**响应**:
```json
{
  "success": true,
  "total_score": 12.5,
  "total_max_score": 22.0,
  "score_rate": 56.8,
  "results": [
    {
      "question_id": "q001",
      "score": 0,
      "max_score": 2.0,
      "correct": false,
      "feedback": "正确答案: B"
    }
  ]
}
```

---

## 十二、版本管理接口

### 12.1 废止文档

```
POST /collections/<kb_name>/documents/<path:filename>/deprecate
```

**请求体**:
```json
{
  "reason": "制度已更新"
}
```

### 12.2 恢复文档

```
POST /collections/<kb_name>/documents/<path:filename>/restore
```

### 12.3 版本历史

```
GET /collections/<kb_name>/documents/<path:filename>/versions
```

---

## 十三、纲要生成接口

### 13.1 生成纲要

```
POST /outline
```

**请求体**:
```json
{
  "document_id": "员工手册_v2.pdf",
  "force": false
}
```

### 13.2 获取纲要

```
GET /outline/<document_id>
```

### 13.3 导出纲要

```
GET /outline/<document_id>/export?format=markdown
```

### 13.4 纲要列表

```
GET /outline/list
```

---

## 十四、关联推荐接口

### 14.1 获取关联推荐

```
GET /recommend/<document_id>?top_k=5
```

---

## 十五、用户接口

### 15.1 当前用户信息

```
GET /auth/me
```

**响应**:
```json
{
  "user_id": "admin001",
  "username": "管理员",
  "role": "admin",
  "department": "技术部"
}
```

### 15.2 系统统计

```
GET /stats
```

**响应**:
```json
{
  "total_messages": 176,
  "total_sessions": 25,
  "total_users": 2
}
```

---

## 十七、企业文件系统集成

### 17.1 概述

RAG 服务支持从企业现有文件系统获取文件进行向量化，无需在本地存储重复文件。

**当前对接模式**: 本地存储

文件存储在 RAG 服务的 `documents/` 目录下，按知识库组织：

```
documents/
├── public_kb/          # 公开知识库
│   ├── 文档1.pdf
│   └── 文档2.docx
├── dept_finance/       # 财务部知识库
│   └── 报销制度.pdf
└── dept_hr/            # 人事部知识库
    └── 员工手册.docx
```

### 17.2 文件上传流程

**方式一: 直接上传到 RAG 服务**

```http
POST /documents/upload
Content-Type: multipart/form-data

file: (二进制文件)
collection: public_kb
```

**响应**:
```json
{
  "success": true,
  "message": "文件上传成功",
  "file": {
    "filename": "文档名.pdf",
    "collection": "public_kb",
    "path": "public_kb/文档名.pdf",
    "size": 1024000
  },
  "chunk_count": 15
}
```

**方式二: 后端转发（推荐）**

```
前端 → 后端 → RAG服务
              ↓
         存储到 documents/
              ↓
         解析 + 向量化
              ↓
         返回 chunk_count
              ↓
    后端存储元数据到数据库
```

后端示例：
```python
@app.route('/api/documents/upload', methods=['POST'])
def upload_document():
    file = request.files['file']
    kb_name = request.form.get('kb_name', 'public_kb')

    # 转发到 RAG 服务
    response = requests.post(
        'http://rag-service:5001/documents/upload',
        files={'file': file},
        data={'collection': kb_name}
    )

    result = response.json()

    # 存储元数据到后端数据库
    if result.get('success'):
        db.execute("""
            INSERT INTO file_index (filename, kb_name, size, chunk_count, uploaded_by)
            VALUES (?, ?, ?, ?, ?)
        """, (
            result['file']['filename'],
            kb_name,
            result['file']['size'],
            result.get('chunk_count', 0),
            current_user.id
        ))

    return jsonify(result)
```

### 17.3 文档目录结构

后端需要了解 RAG 服务的文档目录结构：

| 路径 | 说明 |
|------|------|
| `documents/public_kb/` | 公开知识库文件 |
| `documents/dept_<name>/` | 部门知识库文件 |
| `knowledge/vector_store/chroma/` | ChromaDB 向量数据 |
| `knowledge/vector_store/bm25/` | BM25 索引 |

### 17.4 后续扩展

后续可切换到企业文件系统集成，配置方式：

```bash
# 切换存储类型
STORAGE_TYPE=s3  # 或 smb / http

# S3 配置
STORAGE_S3_ENDPOINT=http://minio.example.com:9000
STORAGE_S3_BUCKET=documents
STORAGE_S3_ACCESS_KEY=xxx
STORAGE_S3_SECRET_KEY=xxx
```

切换后，RAG 服务将从企业文件系统读取文件，无需本地存储。

---

## 十八、接口速查表

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/health` | ❌ | 健康检查 |
| GET | `/auth/me` | Header | 当前用户信息 |
| GET | `/stats` | Header | 系统统计 |
| POST | `/chat` | - | 普通聊天（SSE） |
| POST | `/rag` | - | 知识库问答（SSE） |
| POST | `/search` | - | 混合检索 |
| GET | `/collections` | - | 向量库列表 |
| POST | `/collections` | - | 创建向量库 |
| DELETE | `/collections/<name>` | - | 删除向量库 |
| GET | `/collections/<name>/documents` | - | 向量库文档 |
| GET | `/collections/<name>/chunks` | - | 向量库切片 |
| POST | `/kb/route` | - | 知识库路由测试 |
| POST | `/documents/upload` | - | 上传文档 |
| POST | `/documents/batch-upload` | - | 批量上传 |
| GET | `/documents/list` | - | 文档列表 |
| DELETE | `/documents/<path>` | - | 删除文档 |
| GET | `/documents/<path>/chunks` | - | 文档切片 |
| GET | `/documents/<path>/status` | - | 文档状态 |
| POST | `/chunks` | - | 新增切片 |
| PUT | `/chunks/<id>` | - | 修改切片 |
| DELETE | `/chunks/<id>` | - | 删除切片 |
| GET | `/sync/status` | - | 同步状态 |
| POST | `/sync` | - | 触发同步 |
| GET | `/sync/history` | - | 同步历史 |
| GET | `/sync/changes` | - | 变更日志 |
| POST | `/sync/start` | - | 启动监控 |
| POST | `/sync/stop` | - | 停止监控 |
| GET | `/images/<id>` | - | 获取图片 |
| GET | `/images/<id>/info` | - | 图片信息 |
| GET | `/images/list` | - | 图片列表 |
| GET | `/images/stats` | - | 图片统计 |
| POST | `/feedback` | - | 提交反馈 |
| GET | `/feedback/stats` | - | 反馈统计 |
| GET | `/feedback/list` | - | 反馈列表 |
| GET | `/reports/weekly` | - | 周报告 |
| GET | `/reports/monthly` | - | 月报告 |
| GET | `/faq` | - | FAQ 列表 |
| POST | `/faq` | - | 新增 FAQ |
| PUT | `/faq/<id>` | - | 更新 FAQ |
| DELETE | `/faq/<id>` | - | 删除 FAQ |
| GET | `/faq/suggestions` | - | FAQ 建议 |
| POST | `/faq/suggestions/<id>/approve` | - | 批准建议 |
| POST | `/faq/suggestions/<id>/reject` | - | 拒绝建议 |
| GET | `/exam/health` | - | 出题系统健康检查 |
| POST | `/exam/generate` | - | 生成题目 |
| POST | `/exam/grade` | - | 批改答案 |
| POST | `/collections/<kb>/documents/<file>/deprecate` | - | 废止文档 |
| POST | `/collections/<kb>/documents/<file>/restore` | - | 恢复文档 |
| GET | `/collections/<kb>/documents/<file>/versions` | - | 版本历史 |
| POST | `/outline` | - | 生成纲要 |
| GET | `/outline/<id>` | - | 获取纲要 |
| GET | `/outline/<id>/export` | - | 导出纲要 |
| DELETE | `/outline/<id>` | - | 删除纲要缓存 |
| GET | `/outline/list` | - | 纲要列表 |
| POST | `/outline/batch` | - | 批量生成纲要 |
| GET | `/recommend/<id>` | - | 关联推荐 |

> **说明**: 认证列 `Header` 表示需要传 X-User-ID/X-User-Role 等 Header（开发模式），`-` 表示生产模式不需要认证

---

## 十七、错误响应格式

所有错误响应遵循统一格式：

```json
{
  "error": "错误类型",
  "message": "详细错误信息"
}
```

**常见 HTTP 状态码**:
- `400` - 请求参数错误
- `404` - 资源不存在
- `500` - 服务器内部错误

---

## 十八、后端对接检查清单

**RAG服务部署前**:

- [ ] 设置 `APP_ENV=prod`
- [ ] 配置 `DASHSCOPE_API_KEY`
- [ ] 确认向量模型已下载到 `models/` 目录
- [ ] 确认 `knowledge/vector_store/` 目录已创建

**后端开发前**:

- [ ] 创建会话表（sessions）
- [ ] 创建消息表（messages）
- [ ] 创建知识库权限表（kb_permissions）
- [ ] 实现会话历史查询逻辑
- [ ] 实现权限判断逻辑（生成 collections 列表）
- [ ] 实现 SSE 流式响应消费

**集成测试**:

- [ ] 测试 `/health` 端点
- [ ] 测试 `/rag` SSE 流式响应
- [ ] 测试会话历史传递
- [ ] 测试权限控制（collections 参数）
- [ ] 测试文档上传
- [ ] 测试反馈提交

---

## 更新日志

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2026-04-26 | 3.1 | 根据实际测试结果精简文档，移除无效端点，确保准确性 |
| 2026-04-20 | 3.0 | 合并文档，补充 SSE 详情 |
| 2026-04-13 | 2.0 | 新增同步服务、版本管理等接口 |
