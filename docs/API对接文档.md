# RAG 知识库系统 API 对接文档

## 概述

本文档描述 RAG 知识库系统后端 API 接口，供前端开发人员对接使用。

**基础地址**: `http://localhost:5001`

---

## 1. 认证相关 API

### 1.1 用户登录

**POST** `/auth/login`

**请求体**:
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**响应**:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "user_id": "uuid",
    "username": "admin",
    "role": "admin",
    "department": "技术部"
  }
}
```

**角色说明**:
| 角色 | 权限级别 |
|------|----------|
| admin | 可访问所有级别文档（public, internal, confidential, secret） |
| manager | 可访问 public, internal, confidential |
| user | 可访问 public, internal |

**错误响应**:
```json
{
  "error": "用户名或密码错误"
}
```

---

### 1.2 获取当前用户信息

**GET** `/auth/me`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "user_id": "uuid",
  "username": "admin",
  "role": "admin",
  "department": "技术部",
  "permissions": ["public", "internal", "confidential", "secret"]
}
```

---

### 1.3 修改密码

**POST** `/auth/change-password`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "old_password": "旧密码",
  "new_password": "新密码"
}
```

---

### 1.4 用户管理（仅管理员）

**GET** `/auth/users` - 获取用户列表

**POST** `/auth/register` - 注册新用户
```json
{
  "username": "newuser",
  "password": "password123",
  "role": "user",
  "department": "部门名称"
}
```

**PUT** `/auth/users/<user_id>` - 更新用户信息
```json
{
  "role": "manager",
  "department": "新部门",
  "is_active": true
}
```

**DELETE** `/auth/users/<user_id>` - 删除用户

---

## 2. 聊天/问答 API

### 2.1 普通聊天模式

**POST** `/chat`

**请求头**:
- `Authorization: Bearer <token>`
- `Content-Type: application/json`

**请求体**:
```json
{
  "session_id": null,  // 首次为 null，后续传返回的 session_id
  "message": "你好"
}
```

**响应**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "answer": "你好！有什么我可以帮助你的吗？",
  "mode": "chat",
  "sources": [],
  "web_searched": false
}
```

**说明**:
- 普通聊天模式不使用知识库，支持网络搜索
- `web_searched` 表示是否进行了网络搜索
- 适合日常对话、实时信息查询

---

### 2.2 知识库问答模式（SSE 流式）

**POST** `/rag/stream`

**请求头**:
- `Authorization: Bearer <token>`
- `Content-Type: application/json`

**请求体**:
```json
{
  "session_id": null,
  "message": "出差报销标准是什么？"
}
```

**响应格式**: Server-Sent Events (SSE)

```
data: {"type": "start", "query": "出差报销标准是什么？", "timestamp": 0.0}

data: {"type": "decision", "action": "kb_search", "reason": "首次检索知识库", "iteration": 1, "duration_ms": 500, "timestamp": 0.5}

data: {"type": "retrieve", "source": "知识库", "query": "出差报销标准", "count": 5, "duration_ms": 200, "snippets": [...], "timestamp": 0.7}

data: {"type": "answer", "duration_ms": 1500, "timestamp": 2.2}

data: {"type": "result", "session_id": "550e8400-e29b-41d4-a716-446655440000", "answer": "根据公司规定...", "mode": "rag", "sources": [...]}
```

**事件类型说明**:

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `start` | 开始处理 | `query` |
| `decision` | Agent 决策 | `action`, `reason`, `iteration` |
| `rewrite` | 查询重写 | `old_query`, `new_query` |
| `decompose` | 问题分解 | `sub_queries` |
| `retrieve` | 检索结果 | `source`, `query`, `count`, `snippets` |
| `answer` | 生成答案中 | `duration_ms` |
| `result` | 最终结果 | `session_id`, `answer`, `sources` |
| `error` | 错误 | `message` |

**决策动作说明**:

| action | 说明 |
|--------|------|
| `kb_search` | 知识库检索 |
| `web_search` | 网络搜索 |
| `graph_search` | 知识图谱检索 |
| `answer` | 生成答案 |
| `rewrite` | 重写查询 |
| `decompose` | 分解问题 |

---

### 2.3 知识库问答模式（非流式）

**POST** `/rag`

**请求体**:
```json
{
  "session_id": null,
  "message": "出差报销标准是什么？"
}
```

**响应**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "answer": "根据公司规定...",
  "mode": "rag",
  "sources": [
    {
      "source": "财务管理制度.pdf (第5页)",
      "type": "知识库",
      "count": 2
    }
  ]
}
```

---

## 3. 会话管理 API

### 3.1 获取会话列表

**GET** `/sessions`

**响应**:
```json
{
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2024-01-15T10:30:00",
      "last_active": "2024-01-15T11:00:00",
      "preview": "出差报销标准是什么？..."
    }
  ]
}
```

---

### 3.2 获取会话历史

**GET** `/history/<session_id>`

**响应**:
```json
{
  "history": [
    {
      "role": "user",
      "content": "出差报销标准是什么？",
      "created_at": "2024-01-15T10:30:00"
    },
    {
      "role": "assistant",
      "content": "根据公司规定...",
      "created_at": "2024-01-15T10:30:05"
    }
  ]
}
```

---

### 3.3 删除会话

**DELETE** `/session/<session_id>`

**响应**:
```json
{
  "success": true,
  "message": "会话已删除"
}
```

---

### 3.4 清空会话历史

**POST** `/clear/<session_id>`

---

## 4. 混合检索 API（供外部调用）

### 4.1 混合检索接口

**POST** `/search`

**请求体**:
```json
{
  "query": "查询内容",
  "top_k": 5
}
```

**响应**:
```json
{
  "contexts": ["文档片段1", "文档片段2", ...],
  "metadatas": [
    {"source": "文件名.pdf", "page": 1, "security_level": "public"},
    ...
  ],
  "scores": [0.95, 0.89, ...]
}
```

**说明**: 根据用户权限自动过滤文档，只返回可访问的内容。

---

## 5. 图谱相关 API

### 5.1 获取图谱状态

**GET** `/graph/stats`

**响应**:
```json
{
  "enabled": true,
  "connected": true,
  "nodes": 150,
  "edges": 320,
  "types": ["Person", "Department", "Document", "Process"]
}
```

---

### 5.2 图谱检索

**POST** `/graph/search`

**请求体**:
```json
{
  "query": "财务部门负责什么",
  "top_k": 5,
  "depth": 2
}
```

**响应**:
```json
{
  "answer": "财务部门负责...",
  "entities": ["财务部", "报销审批", "预算管理"],
  "has_graph_context": true,
  "sources": [...],
  "graph_context": "财务部 --负责--> 报销审批..."
}
```

---

### 5.3 重建图谱索引（仅管理员）

**POST** `/graph/build`

---

## 6. 出题系统 API

### 试卷状态流程

```
生成试卷 → draft (草稿)
     ↓
管理员审核 → approved (通过) / rejected (驳回)
     ↓
学生答题 → 批阅 → 生成报告
```

**状态说明**：
| 状态 | 说明 |
|------|------|
| `draft` | 草稿，管理员可在"审核试卷"中审核 |
| `approved` | 已通过，可用于学生答题 |
| `rejected` | 已驳回，不可使用 |

### 6.1 生成试卷

**POST** `/exam/generate`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "name": "Python基础知识测试",
  "topic": "Python基础知识",
  "choice_count": 5,
  "blank_count": 3,
  "short_answer_count": 2,
  "difficulty": 2,
  "choice_score": 2,
  "blank_score": 3,
  "created_by": "admin"
}
```

**参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 试卷名称，默认为"{topic}试卷" |
| `topic` | string | 是 | 试卷主题/知识点 |
| `choice_count` | int | 否 | 选择题数量，默认3 |
| `blank_count` | int | 否 | 填空题数量，默认2 |
| `short_answer_count` | int | 否 | 简答题数量，默认2 |
| `difficulty` | int | 否 | 难度1-5，默认3 |
| `choice_score` | int | 否 | 选择题每题分值，默认2 |
| `blank_score` | int | 否 | 填空题每题分值，默认3 |
| `created_by` | string | 否 | 创建者用户名 |

**响应**:
```json
{
  "exam_id": "uuid",
  "name": "Python基础知识测试",
  "status": "draft",
  "topic": "Python基础知识",
  "created_at": "2024-04-03T10:00:00",
  "created_by": "admin",
  "choice_questions": [
    {
      "id": 1,
      "content": "题目内容",
      "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
      "answer": "B",
      "analysis": "答案解析",
      "knowledge_points": ["知识点1"],
      "difficulty": 2,
      "score": 2
    }
  ],
  "blank_questions": [...],
  "short_answer_questions": [...],
  "total_count": 10,
  "total_score": 25
}
```

---

### 6.2 获取试卷列表

**GET** `/exam/list?status=approved&page=1&limit=20`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `status`: 状态过滤（draft/pending_review/approved/rejected）
- `page`: 页码
- `limit`: 每页数量

**响应**:
```json
{
  "exams": [
    {
      "exam_id": "uuid",
      "name": "Python基础测试",
      "status": "approved",
      "total_count": 10,
      "total_score": 100,
      "created_at": "2024-04-02T10:00:00",
      "created_by": "admin"
    }
  ],
  "total": 5,
  "page": 1
}
```

---

### 6.3 获取试卷详情

**GET** `/exam/<exam_id>`

**请求头**: `Authorization: Bearer <token>`

**响应**: 完整试卷 JSON（包含所有题目）

---

### 6.4 更新试卷

**PUT** `/exam/<exam_id>`

**请求头**: `Authorization: Bearer <token>`

**请求体**: 试卷 JSON（部分或全部字段）

---

### 6.5 删除试卷

**DELETE** `/exam/<exam_id>`

**请求头**: `Authorization: Bearer <token>`

---

### 6.6 提交审核

**POST** `/exam/<exam_id>/submit`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "success": true,
  "status": "pending_review"
}
```

---

### 6.7 审核试卷（仅管理员）

**POST** `/exam/<exam_id>/review`

**请求头**: `Authorization: Bearer <token>`

**整体审核**:
```json
{
  "action": "approve"  // 或 "reject"
}
```

**响应**:
```json
{
  "success": true,
  "exam_id": "uuid",
  "status": "approved",
  "message": "试卷审核通过"
}
```

**说明**：
- `approve`: 审核通过，试卷状态变为 `approved`，可用于学生答题
- `reject`: 驳回，试卷状态变为 `rejected`
- 只有管理员角色可以调用此接口
- 审核通过后试卷会自动保存到题库

---

### 6.8 批阅试卷

**POST** `/exam/<exam_id>/grade`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "student_name": "张三",
  "answers": {
    "choice_1": "A",
    "choice_2": "B",
    "blank_1": "答案内容",
    "short_answer_1": "简答题作答..."
  }
}
```

**响应**:
```json
{
  "report_id": "uuid",
  "exam_id": "uuid",
  "student_name": "张三",
  "graded_at": "2024-04-03T11:00:00",
  "total_score": 15,
  "max_score": 25,
  "score_rate": 60.0,
  "questions": [
    {
      "type": "choice",
      "id": 1,
      "content": "题目内容",
      "student_answer": "A",
      "correct_answer": "B",
      "score": 0,
      "max_score": 2,
      "correct": false
    }
  ]
}
```

---

### 6.9 获取批阅报告

**GET** `/exam/report/<report_id>`

**请求头**: `Authorization: Bearer <token>`

**响应**: 完整批阅报告 JSON

---

### 6.10 批阅报告列表

**GET** `/exam/report/list?page=1&limit=20`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "reports": [
    {
      "report_id": "uuid",
      "exam_id": "uuid",
      "exam_name": "Python基础测试",
      "student_name": "张三",
      "total_score": 15,
      "max_score": 25,
      "score_rate": 60.0,
      "graded_at": "2024-04-03T11:00:00"
    }
  ],
  "total": 10,
  "page": 1
}
```

---

### 6.11 搜索题目

**GET** `/exam/questions/search?keyword=Python&type=choice&difficulty=2`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `keyword`: 搜索关键词
- `type`: 题型过滤（choice/blank/short_answer）
- `difficulty`: 难度过滤（1-5）
- `limit`: 返回数量

**响应**:
```json
{
  "questions": [
    {
      "exam_id": "uuid",
      "exam_name": "Python基础测试",
      "type": "choice",
      "question": {...}
    }
  ],
  "total": 15
}
```

---

## 7. 审计日志 API（仅管理员）

### 7.1 获取审计日志

**GET** `/audit/logs?user_id=xxx&action=rag_query&limit=100&days=7`

**响应**:
```json
{
  "logs": [
    {
      "log_id": 1,
      "user_id": "xxx",
      "username": "testuser",
      "role": "user",
      "action": "rag_query",
      "query": "查询内容",
      "result_summary": "结果摘要...",
      "sources": [...],
      "ip_address": "127.0.0.1",
      "timestamp": "2024-01-15T10:30:00",
      "duration_ms": 1500
    }
  ]
}
```

---

## 8. 系统状态 API

### 8.1 健康检查（无需认证）

**GET** `/health`

**响应**:
```json
{
  "status": "ok",
  "knowledge_base": "150 条记录",
  "bm25_index": "150 个文档",
  "mode": "Agentic RAG"
}
```

---

### 8.2 系统统计（仅管理员）

**GET** `/stats`

**响应**:
```json
{
  "total_sessions": 100,
  "total_messages": 500,
  "active_users": 10
}
```

---

## 9. 权限级别说明

### 文档安全级别

| 级别 | 说明 | 可访问角色 |
|------|------|-----------|
| `public` | 公开文档 | 所有用户 |
| `internal` | 内部文档 | user, manager, admin |
| `confidential` | 机密文档 | manager, admin |
| `secret` | 绝密文档 | admin |

### API 权限要求

| API | 权限要求 |
|-----|----------|
| `/auth/login` | 无需认证 |
| `/health` | 无需认证 |
| `/chat`, `/rag`, `/rag/stream`, `/search` | 需登录 |
| `/sessions`, `/history`, `/session` | 需登录（仅自己的会话） |
| `/exam/generate`, `/exam/list`, `/exam/<id>`, `/exam/<id>/grade` | 需登录 |
| `/exam/<id>/review` | 需 admin 角色 |
| `/auth/users`, `/auth/register`, `/audit/logs` | 需 admin 角色 |
| `/graph/build` | 需 admin 角色 |
| `/stats` | 需 admin 角色 |

---

## 10. 前端对接示例

### 9.1 登录并保存 Token

```javascript
const API_BASE = 'http://localhost:5001';

async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const data = await res.json();
  if (res.ok) {
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    return data;
  }
  throw new Error(data.error);
}
```

---

### 9.2 调用需要认证的 API

```javascript
async function api(endpoint, options = {}) {
  const token = localStorage.getItem('token');
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...options.headers
    }
  });
  if (res.status === 401) {
    // Token 过期，跳转登录
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  return res.json();
}
```

---

### 9.3 知识库问答（SSE 流式）

```javascript
async function ragStream(message, sessionId, onEvent) {
  const token = localStorage.getItem('token');
  const res = await fetch(`${API_BASE}/rag/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ session_id: sessionId, message })
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));
        onEvent(event);
      }
    }
  }
}

// 使用示例
ragStream('有哪些文件可以查看？', null, (event) => {
  console.log(`[${event.type}]`, event);
  if (event.type === 'result') {
    console.log('答案:', event.answer);
    console.log('来源:', event.sources);
  }
});
```

---

### 9.4 显示来源中的安全级别标签

```javascript
function renderSources(sources) {
  return sources.map(s => {
    const level = s.security_level || s.level || '';
    const levelTag = level
      ? `<span class="security-tag ${level}">${level}</span>`
      : '';
    return `<span class="source-item">${levelTag}${s.source}</span>`;
  }).join(', ');
}
```

---

## 10. 错误处理

所有 API 在出错时返回统一格式：

```json
{
  "error": "错误信息描述"
}
```

常见 HTTP 状态码：
- `400` - 请求参数错误
- `401` - 未认证或 Token 过期
- `403` - 权限不足
- `500` - 服务器内部错误

---

## 11. 特殊问题处理

### 11.1 元问题自动识别

当用户提问以下类型的问题时，系统会自动识别并返回文档列表：
- "有哪些文件可以查看"
- "知识库里有什么"
- "我能访问哪些文档"
- "有什么权限"

响应示例：
```
📚 **知识库文档列表**（共 5 个文档）

1. **财务管理制度.pdf** (30 条片段，权限: public/internal)
2. **员工手册.pdf** (25 条片段，权限: public)
3. **差旅报销规定.pdf** (15 条片段，权限: internal/confidential)
...

**您的权限级别**: public, internal
```

---

## 12. 开发环境启动

```bash
# 启动服务
python rag_api_server.py

# 服务地址
http://localhost:5001

# 测试账号
管理员：admin / admin123
普通用户：testuser / test123
```

---

## 更新日志

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2024-04-03 | 1.1 | 出题系统：添加试卷名称字段、完善审核流程说明 |
| 2024-04-02 | 1.0 | 初始版本 |
