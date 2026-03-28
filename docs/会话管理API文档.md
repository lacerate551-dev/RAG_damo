# 会话管理 API 接口文档

## 概述

本文档描述 RAG 系统的会话管理 API，供前端开发者调用。

**服务地址**: `http://localhost:5001`

**特性**:
- **LLM意图判断**：使用大模型智能判断用户意图
- 多轮对话：记住上下文
- 用户隔离：不同用户会话独立

---

## 意图判断说明

系统使用 **LLM 动态判断** 用户意图，而非固定关键词：

| 意图 | 触发场景 | 处理方式 |
|------|---------|---------|
| **chat** | 问候、感谢、情感表达、闲聊 | 直接调用大模型对话，不检索知识库 |
| **query** | 询问具体信息、流程、规定 | 检索知识库 + Agent决策 |
| **follow_up** | 追问、代词指代 | 结合历史上下文理解后检索 |

**判断示例**:

```
用户: 你好 → chat → 大模型对话
用户: 出差补助标准是什么 → query → 检索知识库
用户: 那请假呢 → follow_up → 结合历史改写查询
用户: 今天心情不好 → chat → 大模型对话
用户: 你真棒 → chat → 大模型对话
```

---

## 1. 发送消息（多轮对话）

### 接口

```
POST /chat
```

### 请求体

```json
{
    "user_id": "用户ID",
    "session_id": "会话ID（首次为null，后续传入返回的session_id）",
    "message": "消息内容"
}
```

### 返回

```json
{
    "session_id": "会话ID",
    "answer": "回复内容",
    "sources": [
        {
            "source": "文件名.pdf",
            "page": 1,
            "snippet": "片段内容..."
        }
    ]
}
```

### 前端调用示例

```javascript
// JavaScript/TypeScript

class RAGClient {
    constructor(baseUrl = 'http://localhost:5001') {
        this.baseUrl = baseUrl;
        this.sessionId = null;
    }

    async chat(userId, message) {
        const response = await fetch(`${this.baseUrl}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                session_id: this.sessionId,
                message: message
            })
        });

        const data = await response.json();
        this.sessionId = data.session_id;  // 保存会话ID
        return data;
    }
}

// 使用
const client = new RAGClient();

// 第一次对话
const result1 = await client.chat('user_123', '出差补助标准是什么？');
console.log(result1.answer);

// 第二次对话（自动带上历史）
const result2 = await client.chat('user_123', '那请假呢？');
console.log(result2.answer);  // 系统知道"那"指的是出差相关的话题
```

---

## 2. 获取用户会话列表

### 接口

```
GET /sessions?user_id=用户ID
```

### 返回

```json
{
    "sessions": [
        {
            "session_id": "会话ID",
            "created_at": "2024-01-01 10:00:00",
            "last_active": "2024-01-01 11:30:00",
            "preview": "最后一条消息预览..."
        }
    ]
}
```

### 前端调用示例

```javascript
async function getSessionList(userId) {
    const response = await fetch(`${baseUrl}/sessions?user_id=${userId}`);
    return await response.json();
}

// 使用
const { sessions } = await getSessionList('user_123');
sessions.forEach(s => {
    console.log(`${s.session_id}: ${s.preview}`);
});
```

---

## 3. 获取会话历史

### 接口

```
GET /history/<session_id>?user_id=用户ID
```

### 返回

```json
{
    "history": [
        {
            "role": "user",
            "content": "消息内容",
            "created_at": "2024-01-01 10:00:00"
        },
        {
            "role": "assistant",
            "content": "回复内容",
            "created_at": "2024-01-01 10:00:05"
        }
    ]
}
```

### 前端调用示例

```javascript
async function getHistory(sessionId, userId) {
    const response = await fetch(
        `${baseUrl}/history/${sessionId}?user_id=${userId}`
    );
    return await response.json();
}

// 渲染聊天记录
const { history } = await getHistory('session_abc', 'user_123');
history.forEach(msg => {
    const className = msg.role === 'user' ? 'user-message' : 'assistant-message';
    renderMessage(className, msg.content);
});
```

---

## 4. 删除会话

### 接口

```
DELETE /session/<session_id>?user_id=用户ID
```

### 返回

```json
{
    "success": true,
    "message": "会话已删除"
}
```

### 前端调用示例

```javascript
async function deleteSession(sessionId, userId) {
    const response = await fetch(
        `${baseUrl}/session/${sessionId}?user_id=${userId}`,
        { method: 'DELETE' }
    );
    return await response.json();
}
```

---

## 5. 清空会话历史

### 接口

```
POST /clear/<session_id>?user_id=用户ID
```

### 返回

```json
{
    "success": true,
    "message": "历史已清空"
}
```

### 前端调用示例

```javascript
async function clearHistory(sessionId, userId) {
    const response = await fetch(
        `${baseUrl}/clear/${sessionId}?user_id=${userId}`,
        { method: 'POST' }
    );
    return await response.json();
}
```

---

## 6. 健康检查

### 接口

```
GET /health
```

### 返回

```json
{
    "status": "ok",
    "knowledge_base": "1234 条记录"
}
```

---

## 7. 统计信息

### 接口

```
GET /stats
```

### 返回

```json
{
    "total_sessions": 10,
    "total_messages": 50,
    "total_users": 3
}
```

---

## 完整前端示例

### React 组件示例

```jsx
import React, { useState, useEffect, useRef } from 'react';

const RAG_CHAT_URL = 'http://localhost:5001';

function ChatApp({ userId }) {
    const [sessionId, setSessionId] = useState(null);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef(null);

    // 发送消息
    const sendMessage = async () => {
        if (!input.trim() || loading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setLoading(true);

        try {
            const response = await fetch(`${RAG_CHAT_URL}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: userId,
                    session_id: sessionId,
                    message: userMessage
                })
            });

            const data = await response.json();
            setSessionId(data.session_id);
            setMessages(prev => [...prev, { role: 'assistant', content: data.answer }]);
        } catch (error) {
            console.error('Error:', error);
            setMessages(prev => [...prev, { role: 'assistant', content: '抱歉，发生了错误。' }]);
        } finally {
            setLoading(false);
        }
    };

    // 加载历史
    const loadHistory = async (sid) => {
        const response = await fetch(
            `${RAG_CHAT_URL}/history/${sid}?user_id=${userId}`
        );
        const data = await response.json();
        setMessages(data.history);
        setSessionId(sid);
    };

    // 新建会话
    const newSession = () => {
        setSessionId(null);
        setMessages([]);
    };

    // 自动滚动到底部
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    return (
        <div className="chat-container">
            <div className="chat-header">
                <button onClick={newSession}>新建会话</button>
                <span>会话: {sessionId?.slice(0, 8) || '新会话'}...</span>
            </div>

            <div className="messages">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`message ${msg.role}`}>
                        {msg.content}
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            <div className="input-area">
                <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyPress={e => e.key === 'Enter' && sendMessage()}
                    placeholder="输入消息..."
                    disabled={loading}
                />
                <button onClick={sendMessage} disabled={loading}>
                    {loading ? '发送中...' : '发送'}
                </button>
            </div>
        </div>
    );
}

export default ChatApp;
```

---

## 会话流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端应用                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  用户A打开聊天                                                   │
│       │                                                         │
│       ▼                                                         │
│  POST /chat {user_id: "A", session_id: null, message: "问题1"}  │
│       │                                                         │
│       ▼                                                         │
│  返回 {session_id: "xxx", answer: "回答1"}                      │
│       │                                                         │
│       │  ← 保存 session_id: "xxx"                               │
│       │                                                         │
│  POST /chat {user_id: "A", session_id: "xxx", message: "问题2"} │
│       │                                                         │
│       ▼                                                         │
│  返回 {session_id: "xxx", answer: "回答2"}  ← 带历史上下文       │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  用户B打开聊天（另一个浏览器/设备）                               │
│       │                                                         │
│       ▼                                                         │
│  POST /chat {user_id: "B", session_id: null, message: "问题1"}  │
│       │                                                         │
│       ▼                                                         │
│  返回 {session_id: "yyy", answer: "回答1"}  ← 独立会话          │
│                                                                 │
│  用户B无法访问 session_id: "xxx"（用户A的会话）                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 注意事项

1. **会话ID管理**：前端需要保存 `session_id`，每次请求时带上
2. **用户ID**：由前端生成或从登录系统获取，必须唯一
3. **用户隔离**：不同 `user_id` 的会话完全隔离
4. **会话过期**：默认24小时，可在后端配置
5. **跨域**：已启用 CORS，支持前端跨域调用

---

## 启动服务

```bash
# 启动 RAG API 服务
python rag_api_server.py

# 服务地址
http://localhost:5001
```

## 测试

```bash
# 运行测试脚本
python test_session_api.py
```
