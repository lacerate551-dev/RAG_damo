# Agentic RAG 速查卡片

## 一、核心流程

```
用户输入
    ↓
意图判断 (LLM)
    ├── chat → 大模型直接对话
    ├── query → 检索知识库
    └── follow_up → 结合历史改写后检索
    ↓
Agent决策循环
    ├── answer → 生成答案
    ├── kb_search → 知识库检索
    ├── web_search → 网络搜索
    ├── rewrite → 改写查询
    └── decompose → 分解问题
    ↓
检索层
    向量检索 + BM25 → RRF融合 → Rerank
    ↓
答案生成 (LLM)
```

---

## 二、意图类型

| 意图 | 场景 | 处理 |
|------|------|------|
| `chat` | 问候、感谢、闲聊 | 大模型对话 |
| `query` | 知识问答 | 检索知识库 |
| `follow_up` | 追问、代词 | 结合历史检索 |

---

## 三、Agent决策

| 决策 | 触发条件 |
|------|---------|
| `answer` | 信息足够 |
| `kb_search` | 需要检索知识库 |
| `web_search` | 需要最新信息 |
| `rewrite` | 查询不准确 |
| `decompose` | 问题复杂 |

---

## 四、检索策略

```python
# 三重检索
向量检索 → 语义相似
BM25检索 → 关键词匹配
Rerank   → 精确重排

# RRF融合
score = weight / (k + rank + 1)
```

---

## 五、使用命令

```bash
# 交互模式
python agentic_rag.py

# 单次问答
python agentic_rag.py "问题"

# 对比模式
python agentic_rag.py --compare "问题"

# API服务
python rag_api_server.py
```

---

## 六、代码调用

```python
from agentic_rag import AgenticRAG

# 初始化
rag = AgenticRAG(
    max_iterations=3,      # 最大迭代次数
    enable_web_search=True # 启用网络搜索
)

# 处理问题
result = rag.process("问题", history=对话历史)

# 获取结果
result['intent']     # 意图类型
result['answer']     # 答案
result['sources']    # 来源
result['iterations'] # 迭代次数
```

---

## 七、API接口

```bash
# 发送消息
POST /chat
{
    "user_id": "用户ID",
    "session_id": "会话ID或null",
    "message": "消息内容"
}

# 返回
{
    "session_id": "会话ID",
    "answer": "答案",
    "intent": "chat/query",
    "sources": [...]
}
```

---

## 八、配置

```python
# config.py (必需)
DASHSCOPE_API_KEY = "your-key"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# config.py (可选)
SERPER_API_KEY = "your-key"  # 网络搜索
```

---

## 九、输出示例

### 闲聊
```
📝 用户: 你好
🎯 意图: chat
回答: 你好呀！今天想了解什么内容？
```

### 知识问答
```
📝 用户: 出差补助标准
🎯 意图: query
🔍 检索: 找到5个片段
回答: 根据规定，出差补助包括...
```

### 追问
```
📝 用户: 出差补助标准？
[回答...]
📝 用户: 那请假呢？
🎯 意图: follow_up
📊 改写: 请假流程
回答: 请假流程如下...
```

---

## 十、文件结构

```
agentic_rag.py      # 主程序
rag_demo.py         # 基础RAG
rag_api_server.py   # API服务
session_manager.py  # 会话管理
chat-ui/            # 前端页面
```
