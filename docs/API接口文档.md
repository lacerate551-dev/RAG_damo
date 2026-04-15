# RAG API Server 接口文档

> **服务地址**: `http://localhost:5001`
> **认证方式**: 网关 Header 注入（详见下方认证说明）
> **跳过**: 所有 `/graph/*` 知识图谱相关 API

---

## 目录

1. [认证说明](#1-认证说明)
2. [基础设施](#2-基础设施)
3. [核心对话](#3-核心对话)
4. [会话管理](#4-会话管理)
5. [多向量库管理](#5-多向量库管理)
6. [文档管理](#6-文档管理)
7. [知识库同步](#7-知识库同步)
8. [订阅与通知](#8-订阅与通知)
9. [出题系统 (/exam)](#9-出题系统)
10. [题库维护](#10-题库维护)
11. [整卷分析](#11-整卷分析)
12. [版本管理](#12-版本管理)
13. [纲要生成](#13-纲要生成)
14. [关联推荐](#14-关联推荐)
15. [问答质量反馈闭环](#15-问答质量反馈闭环)
16. [FAQ 管理](#16-faq-管理)
17. [审计日志](#17-审计日志)

---

## 1. 认证说明

### 认证方式

所有需要认证的接口通过 **HTTP Header** 传递用户信息（由网关注入）：

| Header | 必需 | 说明 |
|---|---|---|
| `X-User-ID` | ✅ | 用户唯一标识 |
| `X-User-Name` | ❌ | 用户名（默认空字符串） |
| `X-User-Role` | ❌ | 用户角色（默认 `user`） |
| `X-User-Department` | ❌ | 所属部门（默认空字符串） |

### 角色权限

| 角色 | 安全级别 | 向量库读取 | 向量库写入 | 向量库删除 | 同步 |
|---|---|---|---|---|---|
| `admin` | public, internal, confidential | 所有 | 所有 | 所有 | 所有 |
| `manager` | public, internal, confidential | public + 本部门 | 本部门 | 本部门 | 本部门 |
| `user` | public, internal | public + 本部门 | ❌ | ❌ | ❌ |

### 开发模式

设置环境变量 `DEV_MODE=true` 后：
- 不传 Header 会自动使用默认测试用户（admin/开发部）
- 支持通过 `Authorization: Bearer mock-token-<username>` 模拟登录

**测试账号**：
| 用户名 | 密码 | 角色 | 部门 |
|---|---|---|---|
| admin | admin123 | admin | 管理部 |
| testuser | test123 | user | 技术部 |
| manager | manager123 | manager | 财务部 |

### 认证失败响应

```json
// 401 - 缺少用户信息
{
  "error": "缺少用户信息",
  "message": "请通过网关访问，或设置 DEV_MODE=true 进行开发测试"
}

// 403 - 权限不足
{
  "error": "权限不足",
  "message": "此接口需要以下角色之一: admin",
  "your_role": "user"
}
```

### 通用 curl 认证 Header 示例

```bash
# Admin 用户
-H "X-User-ID: admin001" \
-H "X-User-Name: 管理员" \
-H "X-User-Role: admin" \
-H "X-User-Department: 技术部"

# Manager 用户
-H "X-User-ID: mgr001" \
-H "X-User-Name: 张经理" \
-H "X-User-Role: manager" \
-H "X-User-Department: finance"

# 普通用户
-H "X-User-ID: user001" \
-H "X-User-Name: 李员工" \
-H "X-User-Role: user" \
-H "X-User-Department: finance"
```

---

## 2. 基础设施

### 2.1 `GET /health` — 健康检查

> **认证**: ❌ 不需要

**curl 示例**:
```bash
curl http://localhost:5001/health
```

**返回** (200):
```json
{
  "status": "ok",
  "knowledge_base": "多向量库模式 (按集合提供服务)",
  "bm25_index": "动态按需加载",
  "mode": "Agentic RAG"
}
```

---

### 2.2 `GET /auth/me` — 获取当前用户信息

> **认证**: ✅ 需要

**curl 示例**:
```bash
curl http://localhost:5001/auth/me \
  -H "X-User-ID: admin001" \
  -H "X-User-Name: 管理员" \
  -H "X-User-Role: admin" \
  -H "X-User-Department: 技术部"
```

**返回** (200):
```json
{
  "user_id": "admin001",
  "username": "管理员",
  "role": "admin",
  "department": "技术部",
  "permissions": ["public", "internal", "confidential"]
}
```

---

### 2.3 `GET /stats` — 系统统计信息

> **认证**: ✅ 需要
> **权限**: 仅 `admin`

**curl 示例**:
```bash
curl http://localhost:5001/stats \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "total_sessions": 42,
  "active_sessions": 15,
  "total_messages": 320,
  "avg_messages_per_session": 7.6
}
```

---

## 3. 核心对话

### 3.1 `POST /chat` — 普通聊天

> **认证**: ✅ 需要
> **说明**: 直接使用 LLM 回复，支持网络搜索，速度快

**请求体**:
```json
{
  "session_id": null,
  "message": "今天天气怎么样？"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `session_id` | string/null | ❌ | 会话 ID，首次传 null 自动创建 |
| `message` | string | ✅ | 消息内容 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/chat \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Name: 测试用户" \
  -H "X-User-Role: user" \
  -d '{"session_id": null, "message": "什么是机器学习？"}'
```

**返回** (200):
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "answer": "机器学习是人工智能的一个分支，它通过数据和算法让计算机能够自动学习和改进...",
  "mode": "chat",
  "sources": [],
  "web_searched": false
}
```

**错误返回** (400):
```json
{
  "error": "缺少 message"
}
```

---

### 3.2 `POST /rag` — 知识库问答

> **认证**: ✅ 需要
> **说明**: 使用 Agentic RAG 从知识库检索回答，支持基于角色的权限过滤

**请求体**:
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "公司的年假制度是什么？"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `session_id` | string/null | ❌ | 会话 ID，首次传 null 自动创建 |
| `message` | string | ✅ | 消息内容 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/rag \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Name: 李员工" \
  -H "X-User-Role: user" \
  -H "X-User-Department: hr" \
  -d '{"session_id": null, "message": "公司的年假制度是什么？"}'
```

**返回** (200):
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "answer": "根据公司制度，员工年假规定如下：\n1. 工作满1年未满10年的，年假5天...",
  "mode": "rag",
  "sources": [
    {
      "source": "员工手册_v2.pdf",
      "snippet": "第五章 假期管理：年假天数根据工龄计算..."
    },
    {
      "source": "考勤管理制度.docx",
      "snippet": "年假应在自然年度内休完..."
    }
  ]
}
```

---

### 3.3 `POST /rag/stream` — 知识库问答（SSE 流式）

> **认证**: ✅ 需要
> **说明**: Server-Sent Events 流式返回，包含决策过程、检索过程、最终结果
> **Content-Type**: `text/event-stream`

**请求体**: 与 `/rag` 相同

```json
{
  "session_id": null,
  "message": "公司出差补贴标准是多少？"
}
```

**curl 示例**:
```bash
curl -N -X POST http://localhost:5001/rag/stream \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -d '{"session_id": null, "message": "公司出差补贴标准是多少？"}'
```

**SSE 流返回**（每行以 `data: ` 开头）:

```
data: {"type": "connected", "message": "开始处理..."}

data: {"type": "start", "query": "出差报销标准是什么？", "timestamp": 0.0}

data: {"type": "decision", "action": "kb_search", "reason": "首次检索知识库", "iteration": 1, "duration_ms": 500, "timestamp": 0.5}

data: {"type": "rewrite", "old_query": "出差报销", "new_query": "差旅费报销标准", "timestamp": 0.6}

data: {"type": "decompose", "sub_queries": ["出差交通费标准", "出差住宿费标准", "出差餐费标准"], "timestamp": 0.7}

data: {"type": "retrieve", "source": "知识库", "query": "出差报销标准", "count": 5, "duration_ms": 200, "snippets": [...], "timestamp": 0.7}

data: {"type": "answer", "duration_ms": 1500, "timestamp": 2.2}

data: {"type": "result", "session_id": "550e8400-e29b-41d4-a716-446655440000", "answer": "根据公司规定...", "mode": "rag", "sources": [...], "log_trace": [...]}
```

**SSE 事件类型**:

| type | 说明 | 关键字段 |
|---|---|---|
| `connected` | 连接建立 | `message` |
| `start` | 开始处理 | `query`, `timestamp` |
| `decision` | Agent 决策 | `action`, `reason`, `iteration`, `duration_ms` |
| `rewrite` | 查询重写 | `old_query`, `new_query` |
| `decompose` | 问题分解 | `sub_queries` |
| `retrieve` | 检索结果 | `source`, `query`, `count`, `snippets` |
| `answer` | 生成答案中 | `duration_ms` |
| `result` | 最终结果 | `session_id`, `answer`, `sources`, `log_trace` |
| `error` | 错误 | `message` |

**决策动作说明**:

| action | 说明 |
|---|---|
| `kb_search` | 知识库检索 |
| `web_search` | 网络搜索 |
| `graph_search` | 知识图谱检索 |
| `answer` | 生成答案 |
| `rewrite` | 重写查询 |
| `decompose` | 分解问题 |

---

### 3.4 `POST /search` — 混合检索（供 Dify 调用）

> **认证**: ✅ 需要
> **说明**: 混合检索接口（向量检索 + BM25 + Rerank），供 Dify 工作流调用

**请求体**:
```json
{
  "query": "财务报销流程",
  "top_k": 5
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `query` | string | ✅ | 查询文本 |
| `top_k` | int | ❌ | 返回数量，默认 5 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/search \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -H "X-User-Department: finance" \
  -d '{"query": "财务报销流程", "top_k": 3}'
```

**返回** (200):
```json
{
  "contexts": [
    "第四章 报销流程：1.填写报销单 2.部门主管审批...",
    "差旅费报销须在出差结束后5个工作日内提交...",
    "报销凭证要求：发票须为增值税普通发票或专用发票..."
  ],
  "metadatas": [
    {"source": "财务管理制度.pdf", "chunk_id": "chunk_42", "security_level": "internal"},
    {"source": "差旅管理规定.docx", "chunk_id": "chunk_8", "security_level": "public"},
    {"source": "财务管理制度.pdf", "chunk_id": "chunk_45", "security_level": "internal"}
  ],
  "scores": [0.95, 0.89, 0.85]
}
```

---

## 4. 会话管理

### 4.1 `GET /sessions` — 获取会话列表

> **认证**: ✅ 需要

**curl 示例**:
```bash
curl http://localhost:5001/sessions \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "sessions": [
    {
      "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "created_at": "2026-04-10T10:00:00",
      "last_active": "2026-04-10T14:30:00",
      "preview": "公司的年假制度是什么？..."
    },
    {
      "session_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "created_at": "2026-04-09T09:00:00",
      "last_active": "2026-04-09T09:15:00",
      "preview": "空会话"
    }
  ]
}
```

---

### 4.2 `GET /history/<session_id>` — 获取会话历史

> **认证**: ✅ 需要
> **限制**: 只能查看自己的会话

**curl 示例**:
```bash
curl http://localhost:5001/history/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "history": [
    {
      "role": "user",
      "content": "公司的年假制度是什么？",
      "created_at": "2026-04-10T10:00:00"
    },
    {
      "role": "assistant",
      "content": "根据公司制度，员工年假规定如下...",
      "created_at": "2026-04-10T10:00:05"
    }
  ]
}
```

**错误返回** (403):
```json
{
  "error": "无权访问此会话"
}
```

---

### 4.3 `DELETE /session/<session_id>` — 删除会话

> **认证**: ✅ 需要
> **限制**: 只能删除自己的会话

**curl 示例**:
```bash
curl -X DELETE http://localhost:5001/session/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "message": "会话已删除"
}
```

---

### 4.4 `POST /clear/<session_id>` — 清空会话历史

> **认证**: ✅ 需要
> **说明**: 保留会话但清空所有消息记录

**curl 示例**:
```bash
curl -X POST http://localhost:5001/clear/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "message": "历史已清空"
}
```

---

## 5. 多向量库管理

### 5.1 `GET /collections` — 获取向量库列表

> **认证**: ✅ 需要
> **说明**: 仅返回当前用户有权限访问的向量库

**curl 示例**:
```bash
curl http://localhost:5001/collections \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -H "X-User-Department: finance"
```

**返回** (200):
```json
{
  "collections": [
    {
      "name": "public_kb",
      "display_name": "公开知识库",
      "document_count": 156,
      "department": "",
      "created_at": "2026-04-01T00:00:00",
      "description": "公开制度文档",
      "can_write": false,
      "can_delete": false,
      "can_sync": false
    },
    {
      "name": "dept_finance",
      "display_name": "财务部知识库",
      "document_count": 42,
      "department": "finance",
      "created_at": "2026-04-02T00:00:00",
      "description": "财务部内部制度",
      "can_write": false,
      "can_delete": false,
      "can_sync": false
    }
  ],
  "total": 2
}
```

---

### 5.2 `POST /collections` — 创建向量库

> **认证**: ✅ 需要
> **权限**: 仅 `admin`

**请求体**:
```json
{
  "name": "dept_marketing",
  "display_name": "市场部知识库",
  "department": "marketing",
  "description": "市场部内部制度和文档"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `name` | string | ✅ | 向量库名（仅字母、数字、下划线） |
| `display_name` | string | ❌ | 展示名称 |
| `department` | string | ❌ | 所属部门 |
| `description` | string | ❌ | 描述 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/collections \
  -H "Content-Type: application/json" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin" \
  -d '{"name": "dept_marketing", "display_name": "市场部知识库", "department": "marketing", "description": "市场部内部文档"}'
```

**返回** (201):
```json
{
  "success": true,
  "message": "向量库 'dept_marketing' 创建成功",
  "name": "dept_marketing"
}
```

**错误返回** (400):
```json
{
  "error": "名称格式错误",
  "message": "向量库名称只能包含字母、数字和下划线"
}
```

---

### 5.3 `DELETE /collections/<kb_name>` — 删除向量库

> **认证**: ✅ 需要
> **权限**: 仅 `admin`

**curl 示例**:
```bash
curl -X DELETE http://localhost:5001/collections/dept_marketing \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "message": "向量库 'dept_marketing' 已删除"
}
```

---

### 5.4 `GET /collections/<kb_name>/documents` — 获取向量库文档列表

> **认证**: ✅ 需要
> **权限**: 需要读权限

**curl 示例**:
```bash
curl http://localhost:5001/collections/public_kb/documents \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -H "X-User-Department: finance"
```

**返回** (200):
```json
{
  "collection": "public_kb",
  "documents": [
    {
      "id": "员工手册_v2.pdf_chunk_0",
      "source": "员工手册_v2.pdf",
      "security_level": "public"
    }
  ],
  "total": 156
}
```

---

### 5.5 `POST /documents/sync` — 触发文档向量化同步

> **认证**: ✅ 需要
> **权限**: `admin` 可同步所有；`manager` 仅本部门

**请求体** (可选):
```json
{
  "collection": "dept_finance"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `collection` | string | ❌ | 目标向量库，不传则同步所有有权限的库 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/documents/sync \
  -H "Content-Type: application/json" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin" \
  -d '{"collection": "public_kb"}'
```

**返回** (200):
```json
{
  "success": true,
  "results": [
    {
      "collection": "public_kb",
      "status": "success",
      "message": "向量库 'public_kb' 同步任务已提交",
      "document_dir": "./documents/public"
    }
  ],
  "synced_count": 1
}
```

---

### 5.6 `POST /kb/route` — 测试知识库路由（调试用）

> **认证**: ✅ 需要

**请求体**:
```json
{
  "query": "财务部的报销流程"
}
```

**curl 示例**:
```bash
curl -X POST http://localhost:5001/kb/route \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -H "X-User-Department: finance" \
  -d '{"query": "财务部的报销流程"}'
```

**返回** (200):
```json
{
  "query": "财务部的报销流程",
  "user_role": "user",
  "user_department": "finance",
  "target_collections": ["public_kb", "dept_finance"],
  "intent": {
    "is_general": false,
    "department": "finance",
    "confidence": 0.92,
    "keywords": ["财务部", "报销"],
    "reason": "查询涉及财务部门相关内容"
  }
}
```

---

## 6. 文档管理

### 6.1 `POST /documents/upload` — 上传文件

> **认证**: ✅ 需要
> **权限**: `admin` 所有库；`manager` 本部门库；`user` 无权限
> **Content-Type**: `multipart/form-data`
> **文件限制**: pdf/docx/doc/xlsx/txt，最大 10MB

**curl 示例**:
```bash
curl -X POST http://localhost:5001/documents/upload \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin" \
  -F "file=@/path/to/document.pdf" \
  -F "collection=public_kb"
```

**返回** (200):
```json
{
  "success": true,
  "message": "文件上传成功，已保存并添加到向量库",
  "file": {
    "filename": "document.pdf",
    "collection": "public_kb",
    "path": "public/document.pdf",
    "size": 245760
  }
}
```

**错误返回** (400):
```json
{
  "error": "不支持的文件类型: .zip，支持: pdf, docx, doc, xlsx, txt"
}
```

---

### 6.2 `GET /documents/list` — 获取文档列表

> **认证**: ✅ 需要
> **参数**: `collection` 过滤向量库（可选）

**curl 示例**:
```bash
# 查看所有可访问的文档
curl "http://localhost:5001/documents/list" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -H "X-User-Department: finance"

# 按向量库过滤
curl "http://localhost:5001/documents/list?collection=public_kb" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "documents": [
    {
      "filename": "员工手册_v2.pdf",
      "collection": "public_kb",
      "path": "public/员工手册_v2.pdf",
      "size": 524288,
      "last_modified": "2026-04-05T14:30:00"
    },
    {
      "filename": "财务制度.docx",
      "collection": "dept_finance",
      "path": "dept_finance/财务制度.docx",
      "size": 102400,
      "last_modified": "2026-04-01T09:00:00"
    }
  ],
  "total": 2
}
```

---

### 6.3 `DELETE /documents/<path:doc_path>` — 删除文档

> **认证**: ✅ 需要
> **权限**: `admin` 所有；`manager` 本部门；`user` 无权限
> **路径参数**: `doc_path` 格式为 `子目录/文件名`

**curl 示例**:
```bash
curl -X DELETE http://localhost:5001/documents/public/old_policy.pdf \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "message": "文档已删除"
}
```

**错误返回** (404):
```json
{
  "error": "文件不存在"
}
```

---

## 7. 知识库同步

### 7.1 `POST /sync` — 手动触发同步

> **认证**: ✅ 需要
> **权限**: 仅 `admin`

**请求体** (可选):
```json
{
  "full_sync": false
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `full_sync` | bool | ❌ | 是否全量同步，默认 false（增量同步） |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/sync \
  -H "Content-Type: application/json" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin" \
  -d '{"full_sync": false}'
```

**返回** (200):
```json
{
  "status": "completed",
  "documents_processed": 5,
  "documents_added": 2,
  "documents_modified": 3,
  "documents_deleted": 0,
  "errors": []
}
```

---

### 7.2 `GET /sync/status` — 获取同步状态

> **认证**: ✅ 需要

**curl 示例**:
```bash
curl http://localhost:5001/sync/status \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "enabled": true,
  "monitoring": false,
  "documents_tracked": 28,
  "unprocessed_changes": 0,
  "last_sync": {
    "sync_id": "sync_20260410_140000",
    "status": "completed",
    "started_at": "2026-04-10T14:00:00",
    "completed_at": "2026-04-10T14:00:15",
    "documents_processed": 3
  },
  "recent_syncs": [...]
}
```

**未启用返回** (200):
```json
{
  "enabled": false,
  "message": "同步服务未启用"
}
```

---

### 7.3 `GET /sync/history` — 获取同步历史

> **认证**: ✅ 需要

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `limit` | int | ❌ | 返回数量，默认 20 |
| `days` | int | ❌ | 最近 N 天，默认 30 |

**curl 示例**:
```bash
curl "http://localhost:5001/sync/history?limit=10&days=7" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "history": [
    {
      "sync_id": "sync_20260410_140000",
      "status": "completed",
      "started_at": "2026-04-10T14:00:00",
      "completed_at": "2026-04-10T14:00:15",
      "documents_processed": 3,
      "documents_added": 1,
      "documents_modified": 2,
      "errors": []
    }
  ]
}
```

---

### 7.4 `GET /sync/changes` — 获取变更日志

> **认证**: ✅ 需要

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `limit` | int | ❌ | 返回数量，默认 50 |
| `processed` | string | ❌ | `true`/`false`，是否已处理 |
| `days` | int | ❌ | 最近 N 天，默认 30 |

**curl 示例**:
```bash
curl "http://localhost:5001/sync/changes?processed=false&limit=20" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "changes": [
    {
      "document_id": "public/新制度.pdf",
      "document_name": "新制度.pdf",
      "change_type": "added",
      "detected_at": "2026-04-10T13:30:00",
      "processed": false
    }
  ]
}
```

---

### 7.5 `POST /sync/start` — 启动文件监控

> **认证**: ✅ 需要
> **权限**: 仅 `admin`

**curl 示例**:
```bash
curl -X POST http://localhost:5001/sync/start \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "message": "文件监控已启动"
}
```

---

### 7.6 `POST /sync/stop` — 停止文件监控

> **认证**: ✅ 需要
> **权限**: 仅 `admin`

**curl 示例**:
```bash
curl -X POST http://localhost:5001/sync/stop \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "message": "文件监控已停止"
}
```

---

## 8. 订阅与通知

### 8.1 `POST /subscribe` — 订阅文档变更

> **认证**: ✅ 需要

**请求体**:
```json
{
  "document_id": "xxx.pdf",
  "document_name": "xxx制度"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `document_id` | string | ❌ | 文档 ID，不填则订阅所有文档 |
| `document_name` | string | ❌ | 文档名称 |

**curl 示例**:
```bash
# 订阅特定文档
curl -X POST http://localhost:5001/subscribe \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -d '{"document_id": "员工手册_v2.pdf"}'

# 订阅所有文档
curl -X POST http://localhost:5001/subscribe \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -d '{}'
```

**返回** (200):
```json
{
  "success": true,
  "message": "已订阅文档: 员工手册_v2.pdf"
}
```

---

### 8.2 `DELETE /subscribe` — 取消订阅

> **认证**: ✅ 需要

**请求体**:
```json
{
  "document_id": "xxx.pdf"
}
```

**curl 示例**:
```bash
curl -X DELETE http://localhost:5001/subscribe \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -d '{"document_id": "员工手册_v2.pdf"}'
```

**返回** (200):
```json
{
  "success": true,
  "message": "已取消订阅"
}
```

---

### 8.3 `GET /subscriptions` — 获取订阅列表

> **认证**: ✅ 需要

**curl 示例**:
```bash
curl http://localhost:5001/subscriptions \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "subscriptions": [
    {
      "document_id": "员工手册_v2.pdf",
      "document_name": "员工手册",
      "created_at": "2026-04-08T10:00:00"
    },
    {
      "document_id": null,
      "document_name": null,
      "created_at": "2026-04-09T09:00:00"
    }
  ]
}
```

---

### 8.4 `GET /notifications` — 获取通知

> **认证**: ✅ 需要

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `unread_only` | string | ❌ | `true`/`false`，仅未读，默认 false |

**curl 示例**:
```bash
curl "http://localhost:5001/notifications?unread_only=true" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "notifications": [
    {
      "id": 1,
      "message": "文档 '员工手册_v2.pdf' 已更新",
      "document_id": "员工手册_v2.pdf",
      "change_type": "modified",
      "read": false,
      "created_at": "2026-04-10T14:00:00"
    }
  ]
}
```

---

### 8.5 `POST /notifications/<notification_id>/read` — 标记已读

> **认证**: ✅ 需要

**curl 示例**:
```bash
curl -X POST http://localhost:5001/notifications/1/read \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "message": "已标记为已读"
}
```

---

### 8.6 `POST /notifications/read-all` — 全部标记已读

> **认证**: ✅ 需要

**curl 示例**:
```bash
curl -X POST http://localhost:5001/notifications/read-all \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "message": "所有通知已标记为已读"
}
```

---

## 9. 出题系统

> **前缀**: `/exam`
> **认证**: 出题系统使用 **JWT Bearer Token**（与主系统的 Header 认证不同）
>
> ```
> Authorization: Bearer <jwt_token>
> ```

### 试卷状态流程

```
生成试卷 → draft (草稿)
     ↓
提交审核 → pending_review (待审核)
     ↓
管理员审核 → approved (通过) / rejected (驳回)
     ↓
学生答题 → 批阅 → 生成报告
```

**状态说明**：
| 状态 | 说明 | 可见范围 |
|---|---|---|
| `draft` | 草稿，刚生成尚未提交审核 | 创建者可见 |
| `pending_review` | 待审核，已提交等待管理员审核 | 管理员可见 |
| `approved` | 已通过，可用于学生答题 | 所有用户可见 |
| `rejected` | 已驳回，不可使用 | 创建者可见 |

### 9.1 `POST /exam/generate` — 生成试卷

> **认证**: ✅ Bearer Token

**请求体**:
```json
{
  "topic": "公司安全生产管理制度",
  "name": "2026年第一季度安全生产考试",
  "choice_count": 5,
  "blank_count": 3,
  "short_answer_count": 2,
  "difficulty": 3,
  "choice_score": 2,
  "blank_score": 3,
  "created_by": "admin001"
}
```

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|---|---|---|---|---|
| `topic` | string | ✅ | - | 试卷主题 |
| `name` | string | ❌ | 自动生成 | 试卷名称 |
| `choice_count` | int | ❌ | 3 | 选择题数量 |
| `blank_count` | int | ❌ | 2 | 填空题数量 |
| `short_answer_count` | int | ❌ | 2 | 简答题数量 |
| `difficulty` | int | ❌ | 3 | 难度 (1-5) |
| `choice_score` | int | ❌ | 2 | 每道选择题分值 |
| `blank_score` | int | ❌ | 3 | 每道填空题分值 |
| `created_by` | string | ❌ | - | 创建者 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/exam/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt_token>" \
  -d '{
    "topic": "公司安全制度",
    "choice_count": 5,
    "blank_count": 3,
    "short_answer_count": 2,
    "difficulty": 3
  }'
```

**返回** (200):
```json
{
  "exam_id": "e1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "name": "公司安全制度-考试",
  "status": "draft",
  "topic": "公司安全制度",
  "difficulty": 3,
  "choice_questions": [
    {
      "id": 1,
      "content": "以下哪项是火灾逃生的正确方式？",
      "options": {"A": "乘坐电梯", "B": "走楼梯", "C": "跳窗", "D": "原地等待"},
      "answer": "B",
      "explanation": "发生火灾时应走消防楼梯...",
      "score": 2
    }
  ],
  "blank_questions": [
    {
      "id": 1,
      "content": "灭火器的有效期为____年。",
      "answer": "2",
      "score": 3
    }
  ],
  "short_answer_questions": [
    {
      "id": 1,
      "content": "请简述火灾应急预案的主要内容。",
      "answer": "火灾应急预案主要包括...",
      "score": 10
    }
  ],
  "total_count": 10,
  "total_score": 25,
  "created_at": "2026-04-10T15:00:00"
}
```

---

### 9.2 `GET /exam/list` — 试卷列表

> **认证**: ✅ Bearer Token

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `status` | string | ❌ | 状态过滤: `draft`/`pending_review`/`approved`/`rejected` |
| `page` | int | ❌ | 页码，默认 1 |
| `limit` | int | ❌ | 每页数量，默认 20 |

**curl 示例**:
```bash
curl "http://localhost:5001/exam/list?status=approved&page=1&limit=10" \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200):
```json
{
  "exams": [
    {
      "exam_id": "e1a2b3c4-...",
      "name": "安全生产考试",
      "status": "approved",
      "topic": "安全生产",
      "total_count": 10,
      "total_score": 100,
      "created_at": "2026-04-10T10:00:00"
    }
  ],
  "total": 5,
  "page": 1
}
```

---

### 9.3 `GET /exam/<exam_id>` — 试卷详情

> **认证**: ✅ Bearer Token

**curl 示例**:
```bash
curl http://localhost:5001/exam/e1a2b3c4-d5e6-7890-abcd-ef1234567890 \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200): 与生成试卷返回的结构相同

---

### 9.4 `PUT /exam/<exam_id>` — 更新试卷

> **认证**: ✅ Bearer Token

**请求体** (部分更新):
```json
{
  "choice_questions": [...],
  "blank_questions": [...]
}
```

**返回** (200): 更新后的完整试卷

---

### 9.5 `DELETE /exam/<exam_id>` — 删除试卷

> **认证**: ✅ Bearer Token

**curl 示例**:
```bash
curl -X DELETE http://localhost:5001/exam/e1a2b3c4-... \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200):
```json
{
  "success": true,
  "message": "试卷已删除"
}
```

---

### 9.6 `POST /exam/<exam_id>/submit` — 提交审核

> **认证**: ✅ Bearer Token

**curl 示例**:
```bash
curl -X POST http://localhost:5001/exam/e1a2b3c4-.../submit \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200):
```json
{
  "success": true,
  "status": "pending_review"
}
```

---

### 9.7 `POST /exam/<exam_id>/review` — 审核试卷

> **认证**: ✅ Bearer Token
> **权限**: 仅 `admin`

**整体审核**:
```json
{
  "action": "approve",
  "feedback": "试卷质量良好，通过审核"
}
```

**逐题审核**:
```json
{
  "action": "partial",
  "questions": [
    {"type": "choice", "id": 1, "approved": true},
    {"type": "choice", "id": 2, "approved": false, "edit": {"content": "修改后的题目内容"}},
    {"type": "blank", "id": 1, "delete": true}
  ]
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `action` | string | ✅ | `approve`/`reject`/`partial` |
| `feedback` | string | ❌ | 审核意见 |
| `questions` | array | `partial` 时必需 | 逐题审核明细 |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/exam/e1a2b3c4-.../review \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt_token>" \
  -d '{"action": "approve", "feedback": "审核通过"}'
```

**返回** (200):
```json
{
  "success": true,
  "status": "approved",
  "message": "试卷已通过审核"
}
```

---

### 9.8 `POST /exam/<exam_id>/grade` — 批阅试卷

> **认证**: ✅ Bearer Token
> **前提**: 试卷状态必须为 `approved`

**请求体**:
```json
{
  "student_name": "张三",
  "answers": {
    "choice_1": "A",
    "choice_2": "B",
    "choice_3": "C",
    "blank_1": "2年",
    "blank_2": "灭火器",
    "short_answer_1": "火灾应急预案主要包括报警、疏散、灭火三个部分..."
  }
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `student_name` | string | ❌ | 考生姓名，默认"匿名" |
| `answers` | object | ✅ | 答案，key 格式: `{题型}_{序号}` |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/exam/e1a2b3c4-.../grade \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt_token>" \
  -d '{
    "student_name": "张三",
    "answers": {
      "choice_1": "B",
      "choice_2": "A",
      "blank_1": "2",
      "short_answer_1": "主要包括..."
    }
  }'
```

**返回** (200):
```json
{
  "report_id": "r1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "exam_id": "e1a2b3c4-...",
  "student_name": "张三",
  "total_score": 15,
  "max_score": 25,
  "score_rate": 60.0,
  "questions": [
    {
      "type": "choice",
      "id": 1,
      "content": "以下哪项是...",
      "student_answer": "B",
      "correct_answer": "B",
      "is_correct": true,
      "score": 2,
      "max_score": 2
    },
    {
      "type": "short_answer",
      "id": 1,
      "content": "请简述...",
      "student_answer": "主要包括...",
      "correct_answer": "火灾应急预案主要包括...",
      "score": 6,
      "max_score": 10,
      "feedback": "要点覆盖不完整，缺少灭火环节"
    }
  ]
}
```

---

### 9.9 `GET /exam/report/<report_id>` — 批阅报告详情

> **认证**: ✅ Bearer Token

**curl 示例**:
```bash
curl http://localhost:5001/exam/report/r1a2b3c4-... \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200): 与批阅返回结构相同

---

### 9.10 `GET /exam/report/list` — 批阅报告列表

> **认证**: ✅ Bearer Token

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `page` | int | ❌ | 页码，默认 1 |
| `limit` | int | ❌ | 每页数量，默认 20 |

**curl 示例**:
```bash
curl "http://localhost:5001/exam/report/list?page=1&limit=10" \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200):
```json
{
  "reports": [...],
  "total": 10,
  "page": 1
}
```

---

### 9.11 `GET /exam/questions/search` — 搜索题目

> **认证**: ✅ Bearer Token

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `keyword` | string | ❌ | 搜索关键词 |
| `type` | string | ❌ | 题型: `choice`/`blank`/`short_answer` |
| `difficulty` | int | ❌ | 难度 1-5 |
| `limit` | int | ❌ | 返回数量，默认 50 |

**curl 示例**:
```bash
curl "http://localhost:5001/exam/questions/search?keyword=安全&type=choice&limit=20" \
  -H "Authorization: Bearer <jwt_token>"
```

**返回** (200):
```json
{
  "questions": [
    {
      "type": "choice",
      "id": 1,
      "content": "以下哪项是...",
      "difficulty": 3,
      "topic": "安全生产"
    }
  ],
  "total": 15
}
```

---

## 10. 题库维护

### 10.1 `POST /questions/link-document` — 建立题目-制度关联

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "question_id": "q001",
  "question_type": "choice",
  "exam_id": "e1a2b3c4-...",
  "document_id": "安全管理制度.pdf",
  "document_name": "安全管理制度",
  "chapter": "第三章 安全生产",
  "key_points": ["安全检查", "隐患排查"],
  "relevance_score": 0.95
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `question_id` | string | ✅ | 题目 ID |
| `question_type` | string | ✅ | `choice`/`blank`/`short_answer` |
| `exam_id` | string | ✅ | 试卷 ID |
| `document_id` | string | ✅ | 制度文档 ID |
| `document_name` | string | ❌ | 文档名 |
| `chapter` | string | ❌ | 章节 |
| `key_points` | array | ❌ | 知识点列表 |
| `relevance_score` | float | ❌ | 关联度，默认 1.0 |

**返回** (200):
```json
{
  "success": true,
  "link_id": 42,
  "message": "题目-制度关联已建立"
}
```

---

### 10.2 `POST /questions/link-knowledge` — 建立题目-知识点关联

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "question_id": "q001",
  "question_type": "choice",
  "exam_id": "e1a2b3c4-...",
  "knowledge_point": "消防安全基础知识",
  "weight": 0.8
}
```

**返回** (200):
```json
{
  "success": true,
  "link_id": 15,
  "message": "题目-知识点关联已建立"
}
```

---

### 10.3 `GET /questions/affected` — 获取受影响题目

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `document_id` | string | ❌ | 文档 ID，不传返回所有受影响题目 |

**curl 示例**:
```bash
curl "http://localhost:5001/questions/affected?document_id=安全管理制度.pdf" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "affected_questions": [
    {
      "question_id": "q001",
      "question_type": "choice",
      "exam_id": "e1a2b3c4-...",
      "document_id": "安全管理制度.pdf",
      "impact_reason": "制度文档已更新",
      "status": "pending_review"
    }
  ],
  "total": 1
}
```

---

### 10.4 `POST /questions/<question_id>/review` — 审核受影响题目

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "question_type": "choice",
  "exam_id": "e1a2b3c4-...",
  "action": "confirm"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `question_type` | string | ✅ | 题型 |
| `exam_id` | string | ✅ | 试卷 ID |
| `action` | string | ✅ | `confirm`（确认有效）/ `update`（标记需更新）/ `disable`（停用） |

**返回** (200):
```json
{
  "success": true,
  "question_id": "q001",
  "action": "confirm",
  "message": "题目已确认有效"
}
```

---

### 10.5 `GET /documents/<document_id>/questions` — 获取制度关联题目

> **认证**: ✅ Header 认证

**curl 示例**:
```bash
curl http://localhost:5001/documents/安全管理制度.pdf/questions \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "document_id": "安全管理制度.pdf",
  "questions": [...],
  "total": 8
}
```

---

### 10.6 `GET /documents/<document_id>/versions` — 获取制度版本历史

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `limit` | int | ❌ | 返回数量，默认 10 |

**返回** (200):
```json
{
  "success": true,
  "document_id": "安全管理制度.pdf",
  "versions": [...],
  "total": 3
}
```

---

### 10.7 `GET /knowledge-points` — 获取知识点列表

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `category` | string | ❌ | 分类过滤 |

**curl 示例**:
```bash
curl "http://localhost:5001/knowledge-points?category=安全" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "knowledge_points": [
    {
      "id": 1,
      "name": "消防安全基础知识",
      "category": "安全",
      "question_count": 12
    }
  ],
  "total": 5
}
```

---

### 10.8 `GET /questions/suggestions` — 获取新题建议

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `document_id` | string | ❌ | 文档 ID 过滤 |
| `status` | string | ❌ | 状态过滤 |

**返回** (200):
```json
{
  "success": true,
  "suggestions": [...],
  "total": 3
}
```

---

### 10.9 `GET /questions/<question_id>/knowledge-points` — 获取题目知识点

> **认证**: ✅ Header 认证

**返回** (200):
```json
{
  "success": true,
  "question_id": "q001",
  "knowledge_points": [
    {
      "id": 1,
      "name": "消防安全基础知识",
      "weight": 0.8
    }
  ],
  "total": 2
}
```

---

## 11. 整卷分析

### 11.1 `POST /exam/<exam_id>/analyze` — 整卷分析

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "grade_report": {
    "total_score": 72,
    "max_score": 100,
    "questions": [
      {"question_id": "q001", "score": 2, "max_score": 2, "is_correct": true},
      {"question_id": "q002", "score": 0, "max_score": 2, "is_correct": false}
    ]
  },
  "question_knowledge_map": {
    "q001": ["消防安全"],
    "q002": ["用电安全"]
  }
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `grade_report` | object | ✅ | 批阅报告 |
| `question_knowledge_map` | object | ❌ | 题目与知识点映射 |

**返回** (200):
```json
{
  "success": true,
  "report": {
    "report_id": "ar001",
    "exam_id": "e1a2b3c4-...",
    "total_score": 72,
    "max_score": 100,
    "score_rate": 72.0,
    "knowledge_analysis": [
      {"point": "消防安全", "correct_rate": 1.0, "status": "掌握"},
      {"point": "用电安全", "correct_rate": 0.0, "status": "薄弱"}
    ],
    "suggestions": ["建议加强用电安全相关知识的学习"],
    "created_at": "2026-04-10T15:00:00"
  }
}
```

---

### 11.2 `GET /analysis/<report_id>` — 获取分析报告

> **认证**: ✅ Header 认证

**返回** (200):
```json
{
  "success": true,
  "report": { ... }
}
```

**错误返回** (404):
```json
{
  "error": "报告不存在"
}
```

---

### 11.3 `GET /analysis/list` — 分析报告列表

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `exam_id` | string | ❌ | 按试卷过滤 |
| `limit` | int | ❌ | 返回数量，默认 20 |

**返回** (200):
```json
{
  "success": true,
  "reports": [...],
  "total": 5
}
```

---

## 12. 版本管理

### 12.1 `POST /documents/<collection>/<path:doc_path>/deprecate` — 废止文档

> **认证**: ✅ Header 认证
> **权限**: `admin` 或 `manager`（本部门）

**请求体**:
```json
{
  "reason": "制度已更新，新版本已发布"
}
```

**curl 示例**:
```bash
curl -X POST http://localhost:5001/documents/public_kb/old_policy.pdf/deprecate \
  -H "Content-Type: application/json" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin" \
  -d '{"reason": "制度已更新"}'
```

**返回** (200):
```json
{
  "success": true,
  "document_id": "old_policy.pdf",
  "collection": "public_kb",
  "status": "deprecated",
  "affected_questions": [...],
  "deprecated_at": "2026-04-10T15:00:00"
}
```

---

### 12.2 `POST /documents/<collection>/<path:doc_path>/restore` — 恢复文档

> **认证**: ✅ Header 认证
> **权限**: `admin` 或 `manager`（本部门）

**curl 示例**:
```bash
curl -X POST http://localhost:5001/documents/public_kb/old_policy.pdf/restore \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "document_id": "old_policy.pdf",
  "collection": "public_kb",
  "status": "active",
  "restored_at": "2026-04-10T15:05:00"
}
```

---

### 12.3 `GET /documents/<collection>/<path:doc_path>/versions` — 版本历史

> **认证**: ✅ Header 认证
> **权限**: 需要读权限

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `limit` | int | ❌ | 返回数量，默认 10 |

**curl 示例**:
```bash
curl "http://localhost:5001/documents/public_kb/员工手册_v2.pdf/versions?limit=5" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "document_id": "员工手册_v2.pdf",
  "collection": "public_kb",
  "versions": [
    {
      "version": 2,
      "status": "active",
      "created_at": "2026-04-05T10:00:00",
      "created_by": "admin001",
      "changes": "更新了假期管理章节"
    },
    {
      "version": 1,
      "status": "deprecated",
      "created_at": "2026-01-15T10:00:00",
      "created_by": "admin001",
      "changes": "初始版本"
    }
  ],
  "total": 2
}
```

---

### 12.4 `GET /documents/<collection>/<path:doc_path>/info` — 文档状态信息

> **认证**: ✅ Header 认证
> **权限**: 需要读权限

**curl 示例**:
```bash
curl http://localhost:5001/documents/public_kb/员工手册_v2.pdf/info \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "document": {
    "document_id": "员工手册_v2.pdf",
    "collection": "public_kb",
    "status": "active",
    "chunk_count": 42,
    "version": 2,
    "last_updated": "2026-04-05T10:00:00"
  }
}
```

---

### 12.5 `GET /documents/deprecated` — 已废止文档列表

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `collection` | string | ❌ | 过滤向量库 |
| `limit` | int | ❌ | 返回数量，默认 50 |

**curl 示例**:
```bash
curl "http://localhost:5001/documents/deprecated?collection=public_kb" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "documents": [
    {
      "document_id": "old_policy.pdf",
      "collection": "public_kb",
      "status": "deprecated",
      "deprecated_at": "2026-04-10T15:00:00",
      "reason": "制度已更新"
    }
  ],
  "total": 1
}
```

---

### 12.6 `POST /search/version-aware` — 版本感知检索

> **认证**: ✅ Header 认证
> **说明**: 自动过滤废止版本，返回相关废止提示

**请求体**:
```json
{
  "query": "年假制度",
  "top_k": 5,
  "include_deprecated": false
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `query` | string | ✅ | 查询内容 |
| `top_k` | int | ❌ | 返回数量，默认 5 |
| `include_deprecated` | bool | ❌ | 是否包含废止文档，默认 false |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/search/version-aware \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -H "X-User-Department: hr" \
  -d '{"query": "年假制度", "top_k": 5}'
```

**返回** (200):
```json
{
  "success": true,
  "query": "年假制度",
  "results": [
    {
      "content": "第五章 假期管理...",
      "source": "员工手册_v2.pdf",
      "score": 0.95
    }
  ],
  "version_hints": [
    {
      "document": "员工手册_v1.pdf",
      "status": "deprecated",
      "reason": "已更新为 v2 版本"
    }
  ],
  "target_collections": ["public_kb", "dept_hr"]
}
```

---

### 12.7 `POST /documents/<collection>/<path:doc_path>/diff` — 版本差异对比

> **认证**: ✅ Header 认证
> **权限**: 需要读权限

**请求体**:
```json
{
  "old_chunks": null,
  "new_chunks": [
    {
      "id": "chunk_1",
      "content": "新版本的内容...",
      "metadata": {"chapter": "第一章"}
    }
  ]
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `old_chunks` | array/null | ❌ | 旧版 chunks，不传则从向量库获取 |
| `new_chunks` | array | ✅ | 新版 chunks |

**返回** (200):
```json
{
  "success": true,
  "document_id": "员工手册_v2.pdf",
  "collection": "public_kb",
  "diff": {
    "added_chunks": [...],
    "modified_chunks": [...],
    "removed_chunks": [...],
    "similarity_threshold": 0.8,
    "total_changes": 5
  }
}
```

---

## 13. 纲要生成

### 13.1 `POST /outline` — 生成文档纲要

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "document_id": "员工手册_v2.pdf",
  "force": false
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `document_id` | string | ✅ | 文档 ID |
| `force` | bool | ❌ | 是否强制重新生成，默认 false |

**curl 示例**:
```bash
curl -X POST http://localhost:5001/outline \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user" \
  -d '{"document_id": "员工手册_v2.pdf"}'
```

**返回** (200):
```json
{
  "success": true,
  "outline": {
    "document_id": "员工手册_v2.pdf",
    "title": "员工手册",
    "sections": [
      {
        "title": "第一章 总则",
        "level": 1,
        "children": [
          {"title": "1.1 适用范围", "level": 2, "summary": "..."},
          {"title": "1.2 基本原则", "level": 2, "summary": "..."}
        ]
      }
    ],
    "generated_at": "2026-04-10T15:00:00"
  }
}
```

---

### 13.2 `GET /outline/<document_id>` — 获取已生成纲要

> **认证**: ✅ Header 认证

**curl 示例**:
```bash
curl http://localhost:5001/outline/员工手册_v2.pdf \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200): 结构同 13.1

**错误返回** (404):
```json
{
  "error": "纲要不存在，请先生成"
}
```

---

### 13.3 `GET /outline/<document_id>/export` — 导出纲要

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `format` | string | ❌ | `json`/`markdown`/`markmap`，默认 json |

**curl 示例**:
```bash
# JSON 格式
curl "http://localhost:5001/outline/员工手册_v2.pdf/export?format=json" \
  -H "X-User-ID: user001" -H "X-User-Role: user"

# Markdown 格式
curl "http://localhost:5001/outline/员工手册_v2.pdf/export?format=markdown" \
  -H "X-User-ID: user001" -H "X-User-Role: user"
```

**返回**:
- `format=json`: Content-Type `application/json; charset=utf-8`
- `format=markdown`/`markmap`: Content-Type `text/plain; charset=utf-8`

---

### 13.4 `DELETE /outline/<document_id>` — 删除纲要缓存

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**返回** (200):
```json
{
  "success": true,
  "message": "缓存已删除"
}
```

---

### 13.5 `GET /outline/list` — 纲要列表

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `limit` | int | ❌ | 返回数量，默认 50 |

**返回** (200):
```json
{
  "success": true,
  "outlines": [
    {
      "document_id": "员工手册_v2.pdf",
      "title": "员工手册",
      "generated_at": "2026-04-10T15:00:00"
    }
  ],
  "total": 3
}
```

---

### 13.6 `POST /outline/batch` — 批量生成纲要

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "document_ids": ["员工手册_v2.pdf", "安全管理制度.pdf"],
  "force": false
}
```

**返回** (200):
```json
{
  "success": true,
  "results": {
    "员工手册_v2.pdf": { ... },
    "安全管理制度.pdf": { ... }
  },
  "total": 2
}
```

---

## 14. 关联推荐

### 14.1 `GET /recommend/<document_id>` — 获取关联推荐

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `top_k` | int | ❌ | 返回数量，默认 5 |
| `cache` | string | ❌ | 是否使用缓存，默认 `true` |

**curl 示例**:
```bash
curl "http://localhost:5001/recommend/员工手册_v2.pdf?top_k=5" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "document_id": "员工手册_v2.pdf",
  "recommendations": [
    {
      "document_id": "考勤管理制度.docx",
      "title": "考勤管理制度",
      "similarity": 0.85,
      "reason": "共同涉及假期管理、考勤规定"
    },
    {
      "document_id": "薪酬管理制度.pdf",
      "title": "薪酬管理制度",
      "similarity": 0.72,
      "reason": "共同涉及员工福利、薪酬计算"
    }
  ],
  "total": 2
}
```

---

### 14.2 `POST /recommend/compute-vectors` — 计算所有文档向量

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**curl 示例**:
```bash
curl -X POST http://localhost:5001/recommend/compute-vectors \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "message": "计算了 28 个文档的向量"
}
```

---

## 15. 问答质量反馈闭环

### 15.1 `POST /feedback` — 提交反馈

> **认证**: ✅ Header 认证

**请求体**:
```json
{
  "session_id": "a1b2c3d4-...",
  "query": "公司的年假制度是什么？",
  "answer": "根据公司制度...",
  "rating": 1,
  "sources": ["员工手册_v2.pdf"],
  "reason": "回答准确且详细",
  "user_id": "user001"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `session_id` | string | ✅ | 会话 ID |
| `query` | string | ✅ | 原始问题 |
| `answer` | string | ❌ | 系统回答 |
| `rating` | int | ✅ | `1`（赞）/ `-1`（踩） |
| `sources` | array | ❌ | 来源文档 |
| `reason` | string | ❌ | 反馈原因 |
| `user_id` | string | ❌ | 用户 ID |

**返回** (200):
```json
{
  "success": true,
  "feedback_id": 42,
  "faq_suggested": true,
  "suggestion_id": 15
}
```

**说明**: 如果正面反馈且问题出现多次，系统会自动建议沉淀为 FAQ。

---

### 15.2 `GET /feedback/stats` — 反馈统计

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `start_date` | string | ❌ | 起始日期 `YYYY-MM-DD` |
| `end_date` | string | ❌ | 结束日期 `YYYY-MM-DD` |

**curl 示例**:
```bash
curl "http://localhost:5001/feedback/stats?start_date=2026-04-01&end_date=2026-04-10" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "stats": {
    "total": 120,
    "positive": 95,
    "negative": 25,
    "positive_rate": 79.2,
    "top_negative_queries": [...]
  }
}
```

---

### 15.3 `GET /feedback/list` — 反馈列表

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `rating` | int | ❌ | 评分过滤: `1` 或 `-1` |
| `user_id` | string | ❌ | 用户过滤 |
| `start_date` | string | ❌ | 起始日期 |
| `end_date` | string | ❌ | 结束日期 |
| `limit` | int | ❌ | 返回数量，默认 100 |

**返回** (200):
```json
{
  "success": true,
  "feedbacks": [
    {
      "feedback_id": 42,
      "session_id": "abc123",
      "query": "年假制度",
      "answer": "...",
      "rating": 1,
      "reason": "回答准确",
      "created_at": "2026-04-10T15:00:00"
    }
  ],
  "total": 120
}
```

---

### 15.4 `GET /reports/weekly` — 周报告

> **认证**: ✅ Header 认证

**返回** (200):
```json
{
  "success": true,
  "report": {
    "period": "weekly",
    "start_date": "2026-04-03",
    "end_date": "2026-04-10",
    "total_queries": 250,
    "positive_feedback": 200,
    "negative_feedback": 20,
    "satisfaction_rate": 90.9,
    "top_queries": [...],
    "improvement_areas": [...]
  }
}
```

---

### 15.5 `GET /reports/monthly` — 月报告

> **认证**: ✅ Header 认证

**返回** (200): 结构同周报告，`period` 为 `monthly`

---

## 16. FAQ 管理

### 16.1 `GET /faq` — FAQ 列表

> **认证**: ✅ Header 认证

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `status` | string | ❌ | 状态过滤 |
| `limit` | int | ❌ | 返回数量，默认 50 |

**curl 示例**:
```bash
curl "http://localhost:5001/faq?limit=20" \
  -H "X-User-ID: user001" \
  -H "X-User-Role: user"
```

**返回** (200):
```json
{
  "success": true,
  "faqs": [
    {
      "faq_id": 1,
      "question": "公司年假制度是什么？",
      "answer": "根据工龄计算...",
      "source_documents": ["员工手册_v2.pdf"],
      "status": "approved",
      "created_at": "2026-04-01T10:00:00"
    }
  ],
  "total": 15
}
```

---

### 16.2 `POST /faq` — 新增 FAQ

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**请求体**:
```json
{
  "question": "如何申请年假？",
  "answer": "通过 OA 系统提交年假申请...",
  "source_documents": ["员工手册_v2.pdf"],
  "status": "approved"
}
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `question` | string | ✅ | 问题 |
| `answer` | string | ✅ | 答案 |
| `source_documents` | array | ❌ | 来源文档 |
| `status` | string | ❌ | 状态，默认 `approved` |

**返回** (200):
```json
{
  "success": true,
  "faq_id": 16,
  "message": "FAQ创建成功"
}
```

---

### 16.3 `PUT /faq/<faq_id>` — 更新 FAQ

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**请求体** (部分更新):
```json
{
  "answer": "更新后的答案...",
  "status": "approved"
}
```

**返回** (200):
```json
{
  "success": true,
  "message": "FAQ更新成功"
}
```

---

### 16.4 `DELETE /faq/<faq_id>` — 删除 FAQ

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**返回** (200):
```json
{
  "success": true,
  "message": "FAQ删除成功"
}
```

---

### 16.5 `GET /faq/suggestions` — FAQ 建议列表

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `status` | string | ❌ | 状态过滤，默认 `pending` |
| `limit` | int | ❌ | 返回数量，默认 50 |

**返回** (200):
```json
{
  "success": true,
  "suggestions": [
    {
      "suggestion_id": 15,
      "question": "出差补贴标准是多少？",
      "proposed_answer": "根据出差地区不同...",
      "source_feedback_id": 42,
      "status": "pending"
    }
  ],
  "total": 3
}
```

---

### 16.6 `POST /faq/suggestions/<suggestion_id>/approve` — 批准建议

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**curl 示例**:
```bash
curl -X POST http://localhost:5001/faq/suggestions/15/approve \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "success": true,
  "faq_id": 17,
  "message": "FAQ建议已批准"
}
```

---

### 16.7 `POST /faq/suggestions/<suggestion_id>/reject` — 拒绝建议

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

**返回** (200):
```json
{
  "success": true,
  "message": "FAQ建议已拒绝"
}
```

---

## 17. 审计日志

### 17.1 `GET /audit/logs` — 获取审计日志

> **认证**: ✅ Header 认证
> **权限**: 仅 `admin`

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `user_id` | string | ❌ | 按用户过滤 |
| `action` | string | ❌ | 按操作类型过滤（如 `rag_query`, `upload_document`, `delete_document`） |
| `limit` | int | ❌ | 返回数量，默认 100 |
| `days` | int | ❌ | 最近 N 天，默认 7 |

**curl 示例**:
```bash
# 查看所有日志
curl "http://localhost:5001/audit/logs?limit=20&days=7" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"

# 按用户过滤
curl "http://localhost:5001/audit/logs?user_id=user001&limit=50" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"

# 按操作类型过滤
curl "http://localhost:5001/audit/logs?action=rag_query&limit=50" \
  -H "X-User-ID: admin001" \
  -H "X-User-Role: admin"
```

**返回** (200):
```json
{
  "logs": [
    {
      "id": 1,
      "user_id": "user001",
      "username": "李员工",
      "role": "user",
      "department": "finance",
      "action": "rag_query",
      "query": "年假制度",
      "result_summary": "根据公司制度...",
      "sources": ["员工手册_v2.pdf"],
      "ip_address": "192.168.1.100",
      "duration_ms": 1200,
      "created_at": "2026-04-10T14:00:00"
    }
  ]
}
```

---

## 附录：接口速查表

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| `GET` | `/health` | ❌ | - | 健康检查 |
| `GET` | `/auth/me` | ✅ | all | 当前用户信息 |
| `GET` | `/stats` | ✅ | admin | 系统统计 |
| `POST` | `/chat` | ✅ | all | 普通聊天 |
| `POST` | `/rag` | ✅ | all | 知识库问答 |
| `POST` | `/rag/stream` | ✅ | all | 知识库问答(SSE) |
| `POST` | `/search` | ✅ | all | 混合检索 |
| `GET` | `/sessions` | ✅ | all | 会话列表 |
| `GET` | `/history/<id>` | ✅ | owner | 会话历史 |
| `DELETE` | `/session/<id>` | ✅ | owner | 删除会话 |
| `POST` | `/clear/<id>` | ✅ | owner | 清空历史 |
| `GET` | `/collections` | ✅ | all | 向量库列表 |
| `POST` | `/collections` | ✅ | admin | 创建向量库 |
| `DELETE` | `/collections/<name>` | ✅ | admin | 删除向量库 |
| `GET` | `/collections/<name>/documents` | ✅ | read | 向量库文档 |
| `POST` | `/documents/sync` | ✅ | admin/mgr | 同步向量化 |
| `POST` | `/kb/route` | ✅ | all | 路由测试 |
| `POST` | `/documents/upload` | ✅ | admin/mgr | 上传文件 |
| `GET` | `/documents/list` | ✅ | all | 文档列表 |
| `DELETE` | `/documents/<path>` | ✅ | admin/mgr | 删除文档 |
| `POST` | `/sync` | ✅ | admin | 手动同步 |
| `GET` | `/sync/status` | ✅ | all | 同步状态 |
| `GET` | `/sync/history` | ✅ | all | 同步历史 |
| `GET` | `/sync/changes` | ✅ | all | 变更日志 |
| `POST` | `/sync/start` | ✅ | admin | 启动监控 |
| `POST` | `/sync/stop` | ✅ | admin | 停止监控 |
| `POST` | `/subscribe` | ✅ | all | 订阅文档 |
| `DELETE` | `/subscribe` | ✅ | all | 取消订阅 |
| `GET` | `/subscriptions` | ✅ | all | 订阅列表 |
| `GET` | `/notifications` | ✅ | all | 获取通知 |
| `POST` | `/notifications/<id>/read` | ✅ | all | 标记已读 |
| `POST` | `/notifications/read-all` | ✅ | all | 全部已读 |
| `POST` | `/exam/generate` | JWT | all | 生成试卷 |
| `GET` | `/exam/list` | JWT | all | 试卷列表 |
| `GET` | `/exam/<id>` | JWT | all | 试卷详情 |
| `PUT` | `/exam/<id>` | JWT | all | 更新试卷 |
| `DELETE` | `/exam/<id>` | JWT | all | 删除试卷 |
| `POST` | `/exam/<id>/submit` | JWT | all | 提交审核 |
| `POST` | `/exam/<id>/review` | JWT | admin | 审核试卷 |
| `POST` | `/exam/<id>/grade` | JWT | all | 批阅试卷 |
| `GET` | `/exam/report/<id>` | JWT | all | 批阅报告 |
| `GET` | `/exam/report/list` | JWT | all | 报告列表 |
| `GET` | `/exam/questions/search` | JWT | all | 搜索题目 |
| `POST` | `/questions/link-document` | ✅ | all | 题目-制度关联 |
| `POST` | `/questions/link-knowledge` | ✅ | all | 题目-知识点关联 |
| `GET` | `/questions/affected` | ✅ | all | 受影响题目 |
| `POST` | `/questions/<id>/review` | ✅ | all | 审核受影响题目 |
| `GET` | `/documents/<id>/questions` | ✅ | all | 制度关联题目 |
| `GET` | `/documents/<id>/versions` | ✅ | all | 制度版本历史 |
| `GET` | `/knowledge-points` | ✅ | all | 知识点列表 |
| `GET` | `/questions/suggestions` | ✅ | all | 新题建议 |
| `GET` | `/questions/<id>/knowledge-points` | ✅ | all | 题目知识点 |
| `POST` | `/exam/<id>/analyze` | ✅ | all | 整卷分析 |
| `GET` | `/analysis/<id>` | ✅ | all | 分析报告 |
| `GET` | `/analysis/list` | ✅ | all | 报告列表 |
| `POST` | `/documents/.../deprecate` | ✅ | admin/mgr | 废止文档 |
| `POST` | `/documents/.../restore` | ✅ | admin/mgr | 恢复文档 |
| `GET` | `/documents/.../versions` | ✅ | read | 版本历史 |
| `GET` | `/documents/.../info` | ✅ | read | 文档状态 |
| `GET` | `/documents/deprecated` | ✅ | all | 废止文档列表 |
| `POST` | `/search/version-aware` | ✅ | all | 版本感知检索 |
| `POST` | `/documents/.../diff` | ✅ | read | 版本差异对比 |
| `POST` | `/outline` | ✅ | all | 生成纲要 |
| `GET` | `/outline/<id>` | ✅ | all | 获取纲要 |
| `GET` | `/outline/<id>/export` | ✅ | all | 导出纲要 |
| `DELETE` | `/outline/<id>` | ✅ | admin | 删除纲要缓存 |
| `GET` | `/outline/list` | ✅ | all | 纲要列表 |
| `POST` | `/outline/batch` | ✅ | all | 批量生成 |
| `GET` | `/recommend/<id>` | ✅ | all | 关联推荐 |
| `POST` | `/recommend/compute-vectors` | ✅ | admin | 计算文档向量 |
| `POST` | `/feedback` | ✅ | all | 提交反馈 |
| `GET` | `/feedback/stats` | ✅ | all | 反馈统计 |
| `GET` | `/feedback/list` | ✅ | all | 反馈列表 |
| `GET` | `/reports/weekly` | ✅ | all | 周报告 |
| `GET` | `/reports/monthly` | ✅ | all | 月报告 |
| `GET` | `/faq` | ✅ | all | FAQ 列表 |
| `POST` | `/faq` | ✅ | admin | 新增 FAQ |
| `PUT` | `/faq/<id>` | ✅ | admin | 更新 FAQ |
| `DELETE` | `/faq/<id>` | ✅ | admin | 删除 FAQ |
| `GET` | `/faq/suggestions` | ✅ | admin | FAQ 建议列表 |
| `POST` | `/faq/suggestions/<id>/approve` | ✅ | admin | 批准建议 |
| `POST` | `/faq/suggestions/<id>/reject` | ✅ | admin | 拒绝建议 |
| `GET` | `/audit/logs` | ✅ | admin | 审计日志 |

> **说明**: ✅ = Header 认证, JWT = Bearer Token 认证, all = 所有已认证用户, owner = 仅会话所有者, read = 需要读权限, admin/mgr = admin 或 manager

---

## 更新日志

| 日期 | 版本 | 更新内容 |
|---|---|---|
| 2026-04-13 | 3.0 | 合并 `api_documentation.md` 和 `API对接文档.md`，补充 SSE 事件类型详情和试卷状态流程说明 |
| 2026-04-10 | 2.1 | 完善出题系统状态流程说明，明确 draft → pending_review → approved/rejected 流程 |
| 2026-04-07 | 2.0 | 新增知识库同步、订阅通知、题库维护、整卷分析、纲要生成、关联推荐、问答质量闭环 API |
| 2024-04-03 | 1.1 | 出题系统：添加试卷名称字段、完善审核流程说明 |
| 2024-04-02 | 1.0 | 初始版本 |
