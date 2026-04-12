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
提交审核 → pending_review (待审核)
     ↓
管理员审核 → approved (通过) / rejected (驳回)
     ↓
学生答题 → 批阅 → 生成报告
```

**状态说明**：
| 状态 | 说明 | 可见范围 |
|------|------|----------|
| `draft` | 草稿，刚生成尚未提交审核 | 创建者可见 |
| `pending_review` | 待审核，已提交等待管理员审核 | 管理员可见 |
| `approved` | 已通过，可用于学生答题 | 所有用户可见 |
| `rejected` | 已驳回，不可使用 | 创建者可见 |

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

**说明**: 将草稿试卷提交审核，状态从 `draft` 变为 `pending_review`。

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
- 审核通过后试卷会自动从草稿目录移动到题库目录

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

## 7. 知识库同步 API

### 7.1 手动触发同步

**POST** `/sync`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**请求体**:
```json
{
  "full_sync": false
}
```

**参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `full_sync` | boolean | 否 | 是否全量同步，默认 false（增量同步） |

**响应**:
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

### 7.2 获取同步状态

**GET** `/sync/status`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "enabled": true,
  "monitoring": true,
  "documents_tracked": 50,
  "unprocessed_changes": 0,
  "last_sync": {
    "sync_id": 1,
    "sync_type": "incremental",
    "status": "completed",
    "start_time": "2026-04-07T10:00:00",
    "end_time": "2026-04-07T10:00:05",
    "documents_processed": 5,
    "error_message": null
  },
  "recent_syncs": [...]
}
```

---

### 7.3 获取同步历史

**GET** `/sync/history?limit=20&days=30`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `limit`: 返回数量（默认20）
- `days`: 最近N天（默认30）

**响应**:
```json
{
  "history": [
    {
      "sync_id": 1,
      "sync_type": "incremental",
      "status": "completed",
      "start_time": "2026-04-07T10:00:00",
      "end_time": "2026-04-07T10:00:05",
      "documents_processed": 5,
      "error_message": null
    }
  ]
}
```

---

### 7.4 获取变更日志

**GET** `/sync/changes?limit=50&processed=true&days=30`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `limit`: 返回数量（默认50）
- `processed`: 是否已处理（可选，true/false）
- `days`: 最近N天（默认30）

**响应**:
```json
{
  "changes": [
    {
      "id": 1,
      "document_id": "财务管理制度.pdf",
      "change_type": "modified",
      "old_hash": "abc123",
      "new_hash": "def456",
      "change_time": "2026-04-07T10:00:00",
      "processed": 1
    }
  ]
}
```

---

### 7.5 启动文件监控

**POST** `/sync/start`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**响应**:
```json
{
  "message": "文件监控已启动"
}
```

---

### 7.6 停止文件监控

**POST** `/sync/stop`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**响应**:
```json
{
  "message": "文件监控已停止"
}
```

---

## 8. 订阅与通知 API

### 8.1 订阅文档变更

**POST** `/subscribe`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "document_id": "财务管理制度.pdf",
  "document_name": "财务管理制度"
}
```

**说明**: `document_id` 不填则订阅所有文档变更通知。

**响应**:
```json
{
  "success": true,
  "message": "已订阅文档: 财务管理制度.pdf"
}
```

---

### 8.2 取消订阅

**DELETE** `/subscribe`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "document_id": "财务管理制度.pdf"
}
```

**响应**:
```json
{
  "success": true,
  "message": "已取消订阅"
}
```

---

### 8.3 获取订阅列表

**GET** `/subscriptions`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "subscriptions": [
    {
      "document_id": "财务管理制度.pdf",
      "document_name": "财务管理制度",
      "created_at": "2026-04-07T10:00:00"
    }
  ]
}
```

---

### 8.4 获取通知列表

**GET** `/notifications?unread_only=false`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `unread_only`: 是否只显示未读（默认false）

**响应**:
```json
{
  "notifications": [
    {
      "id": 1,
      "user_id": "xxx",
      "document_id": "财务管理制度.pdf",
      "document_name": "财务管理制度",
      "change_type": "modified",
      "message": "文档已更新",
      "created_at": "2026-04-07T10:00:00",
      "read": 0
    }
  ]
}
```

---

### 8.5 标记通知已读

**POST** `/notifications/<notification_id>/read`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "success": true,
  "message": "已标记为已读"
}
```

---

### 8.6 全部标记已读

**POST** `/notifications/read-all`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "success": true,
  "message": "所有通知已标记为已读"
}
```

---

## 9. 题库维护 API

### 9.1 建立题目-制度关联

**POST** `/questions/link-document`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "question_id": "q_001",
  "question_type": "choice",
  "exam_id": "exam_uuid",
  "document_id": "财务管理制度.pdf",
  "document_name": "财务管理制度",
  "chapter": "第三章 报销管理",
  "key_points": ["报销标准", "审批流程"],
  "relevance_score": 0.95
}
```

**响应**:
```json
{
  "success": true,
  "link_id": 1,
  "message": "题目-制度关联已建立"
}
```

---

### 9.2 建立题目-知识点关联

**POST** `/questions/link-knowledge`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "question_id": "q_001",
  "question_type": "choice",
  "exam_id": "exam_uuid",
  "knowledge_point": "报销审批流程",
  "weight": 1.0
}
```

**响应**:
```json
{
  "success": true,
  "link_id": 1,
  "message": "题目-知识点关联已建立"
}
```

---

### 9.3 获取受影响题目

**GET** `/questions/affected?document_id=财务管理制度.pdf`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `document_id`: 文档ID（可选，不填则返回所有）

**响应**:
```json
{
  "success": true,
  "affected_questions": [
    {
      "question_id": "q_001",
      "question_type": "choice",
      "exam_id": "exam_uuid",
      "document_id": "财务管理制度.pdf",
      "chapter": "第三章",
      "status": "affected"
    }
  ],
  "total": 1
}
```

---

### 9.4 审核受影响题目

**POST** `/questions/<question_id>/review`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "question_type": "choice",
  "exam_id": "exam_uuid",
  "action": "confirm"
}
```

**action 说明**:
| 值 | 说明 |
|----|------|
| `confirm` | 确认题目仍然有效 |
| `update` | 需要更新题目内容 |
| `disable` | 禁用题目 |

**响应**:
```json
{
  "success": true,
  "message": "题目已确认"
}
```

---

### 9.5 获取制度关联题目

**GET** `/documents/<document_id>/questions`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "success": true,
  "document_id": "财务管理制度.pdf",
  "questions": [
    {
      "question_id": "q_001",
      "question_type": "choice",
      "exam_id": "exam_uuid",
      "chapter": "第三章",
      "key_points": ["报销标准"],
      "relevance_score": 0.95
    }
  ],
  "total": 1
}
```

---

### 9.6 获取制度版本历史

**GET** `/documents/<document_id>/versions?limit=10`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `limit`: 返回数量（默认10）

**响应**:
```json
{
  "success": true,
  "document_id": "财务管理制度.pdf",
  "versions": [
    {
      "id": 1,
      "document_id": "财务管理制度.pdf",
      "version": "v1.2",
      "content_hash": "def456",
      "change_summary": "更新了报销标准章节",
      "changed_sections": ["第三章"],
      "created_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 9.7 获取知识点列表

**GET** `/knowledge-points?category=财务`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `category`: 分类过滤（可选）

**响应**:
```json
{
  "success": true,
  "knowledge_points": [
    {
      "id": 1,
      "knowledge_point": "报销审批流程",
      "category": "财务",
      "created_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 9.8 获取新题建议

**GET** `/questions/suggestions?document_id=xxx&status=pending`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `document_id`: 文档ID（可选）
- `status`: 状态过滤（pending/approved/rejected，可选）

**响应**:
```json
{
  "success": true,
  "suggestions": [
    {
      "id": 1,
      "document_id": "财务管理制度.pdf",
      "suggestion_type": "new_question",
      "question_type": "choice",
      "suggested_content": "题目内容建议...",
      "reason": "新增章节内容",
      "status": "pending",
      "created_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

## 10. 整卷分析 API

### 10.1 整卷分析

**POST** `/exam/<exam_id>/analyze`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "grade_report": {
    "exam_id": "exam_uuid",
    "student_name": "张三",
    "total_score": 85,
    "max_score": 100,
    "questions": [...]
  },
  "question_knowledge_map": {
    "q_001": ["报销流程", "审批权限"],
    "q_002": ["预算管理"]
  }
}
```

**响应**:
```json
{
  "success": true,
  "report": {
    "report_id": "report_uuid",
    "exam_id": "exam_uuid",
    "student_name": "张三",
    "total_score": 85,
    "max_score": 100,
    "score_rate": 0.85,
    "type_scores": {
      "choice": {"score": 40, "max": 40, "rate": 1.0},
      "blank": {"score": 20, "max": 30, "rate": 0.67},
      "short_answer": {"score": 25, "max": 30, "rate": 0.83}
    },
    "weak_points": [
      {
        "knowledge_point": "预算管理",
        "score_rate": 0.5,
        "question_count": 2
      }
    ],
    "strong_points": [
      {
        "knowledge_point": "报销流程",
        "score_rate": 1.0,
        "question_count": 3
      }
    ],
    "ai_comment": "整体表现良好，选择题满分...",
    "study_suggestions": [
      {
        "knowledge_point": "预算管理",
        "suggestion": "建议重点复习预算编制流程...",
        "related_documents": ["预算管理办法.pdf"]
      }
    ],
    "created_at": "2026-04-07T10:00:00"
  }
}
```

---

### 10.2 获取分析报告

**GET** `/analysis/<report_id>`

**请求头**: `Authorization: Bearer <token>`

**响应**: 完整分析报告 JSON

---

### 10.3 分析报告列表

**GET** `/analysis/list?exam_id=xxx&limit=20`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `exam_id`: 试卷ID（可选）
- `limit`: 返回数量（默认20）

**响应**:
```json
{
  "success": true,
  "reports": [
    {
      "report_id": "report_uuid",
      "exam_id": "exam_uuid",
      "student_name": "张三",
      "total_score": 85,
      "score_rate": 0.85,
      "created_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 10.4 获取题目知识点

**GET** `/questions/<question_id>/knowledge-points`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "success": true,
  "question_id": "q_001",
  "knowledge_points": [
    {
      "knowledge_point": "报销流程",
      "weight": 1.0
    }
  ],
  "total": 1
}
```

---

## 11. 纲要生成 API

### 11.1 生成文档纲要

**POST** `/outline`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "document_id": "财务管理制度.pdf",
  "force": false
}
```

**参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `document_id` | string | 是 | 文档ID（文件名） |
| `force` | boolean | 否 | 是否强制重新生成，默认 false（使用缓存） |

**响应**:
```json
{
  "success": true,
  "outline": {
    "document_id": "财务管理制度.pdf",
    "document_name": "财务管理制度",
    "total_pages": 15,
    "generated_at": "2026-04-07T10:00:00",
    "outline": [
      {
        "id": "node_1",
        "title": "第一章 总则",
        "summary": "制度目的、适用范围、基本原则",
        "level": 1,
        "order": 1,
        "page": 1,
        "children": [
          {
            "id": "node_1_1",
            "title": "1.1 目的",
            "summary": "规范财务管理，提高资金使用效率",
            "level": 2,
            "order": 1,
            "children": []
          }
        ]
      }
    ],
    "export_formats": ["json", "markdown", "markmap"]
  }
}
```

---

### 11.2 获取已生成的纲要

**GET** `/outline/<document_id>`

**请求头**: `Authorization: Bearer <token>`

**响应**: 同 11.1 生成纲要响应

---

### 11.3 导出纲要

**GET** `/outline/<document_id>/export?format=json`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `format`: 导出格式（json/markdown/markmap）

**响应**:
- `json`: 返回 JSON 格式
- `markdown`: 返回 Markdown 格式
- `markmap`: 返回 Markmap 兼容的 Markdown 格式

**Markdown 示例**:
```markdown
# 财务管理制度

## 第一章 总则

目的：规范财务管理，提高资金使用效率

### 1.1 目的

规范财务管理，提高资金使用效率
```

---

### 11.4 删除纲要缓存

**DELETE** `/outline/<document_id>`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**响应**:
```json
{
  "success": true,
  "message": "缓存已删除"
}
```

---

### 11.5 获取纲要列表

**GET** `/outline/list?limit=50`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `limit`: 返回数量（默认50）

**响应**:
```json
{
  "success": true,
  "outlines": [
    {
      "document_id": "财务管理制度.pdf",
      "document_name": "财务管理制度",
      "generated_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 11.6 批量生成纲要

**POST** `/outline/batch`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "document_ids": ["财务管理制度.pdf", "差旅管理办法.pdf"],
  "force": false
}
```

**响应**:
```json
{
  "success": true,
  "results": {
    "财务管理制度.pdf": { /* 纲要内容 */ },
    "差旅管理办法.pdf": { /* 纲要内容 */ }
  },
  "total": 2
}
```

---

## 12. 关联推荐 API

### 12.1 获取关联推荐

**GET** `/recommend/<document_id>?top_k=5&cache=true`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `top_k`: 返回数量（默认5）
- `cache`: 是否使用缓存（默认true）

**响应**:
```json
{
  "success": true,
  "document_id": "财务管理制度.pdf",
  "recommendations": [
    {
      "document_id": "差旅管理办法.pdf",
      "document_name": "差旅管理办法",
      "similarity": 0.85,
      "tag_score": 0.3,
      "final_score": 0.68,
      "tags": ["财务", "报销"]
    }
  ],
  "total": 1
}
```

---

### 12.2 计算所有文档向量

**POST** `/recommend/compute-vectors`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**说明**: 初始化或更新所有文档的向量表示，用于相似度计算。

**响应**:
```json
{
  "success": true,
  "message": "计算了 50 个文档的向量"
}
```

---

## 13. 问答质量闭环 API

### 13.1 提交反馈

**POST** `/feedback`

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "出差报销标准是什么？",
  "answer": "根据公司规定...",
  "rating": 1,
  "sources": [{"source": "财务管理制度.pdf", "snippet": "..."}],
  "reason": "",
  "user_id": "user001"
}
```

**参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 会话ID |
| `query` | string | 是 | 用户问题 |
| `answer` | string | 否 | 系统回答 |
| `rating` | int | 是 | 评分：1=赞，-1=踩 |
| `sources` | array | 否 | 来源文档列表 |
| `reason` | string | 否 | 点踩原因 |
| `user_id` | string | 否 | 用户ID |

**响应**:
```json
{
  "success": true,
  "feedback_id": 1,
  "faq_suggested": true,
  "suggestion_id": 5
}
```

**说明**: 如果正面反馈且问题出现多次，系统会自动建议沉淀为 FAQ。

---

### 13.2 获取反馈统计

**GET** `/feedback/stats?start_date=2026-04-01&end_date=2026-04-07`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `start_date`: 开始日期（可选）
- `end_date`: 结束日期（可选）

**响应**:
```json
{
  "success": true,
  "stats": {
    "total_queries": 1000,
    "positive_count": 850,
    "negative_count": 150,
    "positive_rate": 0.85,
    "avg_rating": 0.7,
    "period": {
      "start": "2026-04-01",
      "end": "2026-04-07"
    }
  }
}
```

---

### 13.3 获取反馈列表

**GET** `/feedback/list?rating=-1&limit=100`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `rating`: 评分过滤（1/-1，可选）
- `user_id`: 用户ID过滤（可选）
- `start_date`: 开始日期（可选）
- `end_date`: 结束日期（可选）
- `limit`: 返回数量（默认100）

**响应**:
```json
{
  "success": true,
  "feedbacks": [
    {
      "id": 1,
      "session_id": "xxx",
      "query": "问题内容",
      "answer": "回答内容",
      "rating": -1,
      "reason": "回答不准确",
      "created_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 13.4 获取周报告

**GET** `/reports/weekly`

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "success": true,
  "report": {
    "report_id": "weekly_2026_14",
    "report_type": "weekly",
    "period_start": "2026-04-01",
    "period_end": "2026-04-07",
    "total_queries": 500,
    "avg_rating": 0.75,
    "positive_rate": 0.85,
    "low_rating_queries": [
      {
        "query": "问题内容",
        "avg_rating": -0.5,
        "count": 3
      }
    ],
    "high_freq_queries": [
      {
        "query": "报销标准",
        "count": 50,
        "avg_rating": 0.9
      }
    ],
    "improvement_suggestions": [
      "建议优化「报销标准」相关问题的回答准确性"
    ],
    "generated_at": "2026-04-07T10:00:00"
  }
}
```

---

### 13.5 获取月报告

**GET** `/reports/monthly`

**请求头**: `Authorization: Bearer <token>`

**响应**: 同周报告格式

---

### 13.6 获取FAQ列表

**GET** `/faq?status=approved&limit=50`

**请求头**: `Authorization: Bearer <token>`

**参数**:
- `status`: 状态过滤（draft/approved/disabled，可选）
- `limit`: 返回数量（默认50）

**响应**:
```json
{
  "success": true,
  "faqs": [
    {
      "id": 1,
      "question": "出差报销标准是什么？",
      "answer": "根据公司规定...",
      "source_documents": ["财务管理制度.pdf"],
      "frequency": 25,
      "avg_rating": 0.9,
      "status": "approved",
      "created_at": "2026-04-07T10:00:00",
      "updated_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 13.7 新增FAQ

**POST** `/faq`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**请求体**:
```json
{
  "question": "出差报销标准是什么？",
  "answer": "根据公司规定...",
  "source_documents": ["财务管理制度.pdf"],
  "status": "approved"
}
```

**响应**:
```json
{
  "success": true,
  "faq_id": 1,
  "message": "FAQ创建成功"
}
```

---

### 13.8 更新FAQ

**PUT** `/faq/<faq_id>`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**请求体**:
```json
{
  "question": "更新后的问题",
  "answer": "更新后的答案",
  "status": "approved"
}
```

**响应**:
```json
{
  "success": true,
  "message": "FAQ更新成功"
}
```

---

### 13.9 删除FAQ

**DELETE** `/faq/<faq_id>`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**响应**:
```json
{
  "success": true,
  "message": "FAQ删除成功"
}
```

---

### 13.10 获取FAQ建议列表

**GET** `/faq/suggestions?status=pending&limit=50`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**参数**:
- `status`: 状态过滤（pending/approved/rejected，默认pending）
- `limit`: 返回数量（默认50）

**响应**:
```json
{
  "success": true,
  "suggestions": [
    {
      "id": 1,
      "query": "出差报销标准是什么？",
      "answer": "根据公司规定...",
      "frequency": 10,
      "avg_rating": 0.8,
      "status": "pending",
      "created_at": "2026-04-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 13.11 批准FAQ建议

**POST** `/faq/suggestions/<suggestion_id>/approve`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**响应**:
```json
{
  "success": true,
  "faq_id": 1,
  "message": "FAQ建议已批准"
}
```

---

### 13.12 拒绝FAQ建议

**POST** `/faq/suggestions/<suggestion_id>/reject`

**请求头**: `Authorization: Bearer <token>`（需管理员权限）

**响应**:
```json
{
  "success": true,
  "message": "FAQ建议已拒绝"
}
```

---

## 14. API 权限速查表

| API 路径 | 方法 | 权限要求 |
|---------|------|----------|
| `/auth/login` | POST | 无需认证 |
| `/health` | GET | 无需认证 |
| `/chat`, `/rag`, `/rag/stream`, `/search` | POST | 需登录 |
| `/sessions`, `/history`, `/session` | GET/DELETE | 需登录 |
| `/sync` | POST | 需 admin |
| `/sync/status`, `/sync/history`, `/sync/changes` | GET | 需登录 |
| `/sync/start`, `/sync/stop` | POST | 需 admin |
| `/subscribe`, `/subscriptions` | POST/GET/DELETE | 需登录 |
| `/notifications` | GET/POST | 需登录 |
| `/questions/*` | GET/POST | 需登录 |
| `/exam/*` | GET/POST | 需登录 |
| `/exam/<id>/review` | POST | 需 admin |
| `/outline` | POST | 需登录 |
| `/outline/<id>` | DELETE | 需 admin |
| `/recommend/*` | GET | 需登录 |
| `/recommend/compute-vectors` | POST | 需 admin |
| `/feedback` | POST | 需登录 |
| `/reports/*` | GET | 需登录 |
| `/faq` | GET | 需登录 |
| `/faq` | POST | 需 admin |
| `/faq/<id>` | PUT/DELETE | 需 admin |
| `/faq/suggestions/*` | GET/POST | 需 admin |
| `/auth/users`, `/auth/register`, `/audit/logs` | GET/POST | 需 admin |
| `/graph/build` | POST | 需 admin |
| `/stats` | GET | 需 admin |

---

## 15. 开发环境启动

```bash
# 激活虚拟环境
.\venv\Scripts\Activate.ps1

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
| 2026-04-07 | 2.1 | 完善出题系统状态流程说明，明确 draft → pending_review → approved/rejected 流程 |
| 2026-04-07 | 2.0 | 新增知识库同步、订阅通知、题库维护、整卷分析、纲要生成、关联推荐、问答质量闭环 API |
| 2024-04-03 | 1.1 | 出题系统：添加试卷名称字段、完善审核流程说明 |
| 2024-04-02 | 1.0 | 初始版本 |
