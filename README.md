# RAG Demo - 本地知识库问答系统

基于本地向量模型 + Chroma向量数据库 + Qwen API 的智能知识库问答系统，支持双模式对话和Agentic RAG。

## 功能特性

### v3.0.0 新特性
- **双模式切换**：普通聊天(qwen3.5-flash) / 知识库问答(qwen3.5-plus)
- **会话管理**：SQLite 持久化，支持多用户多会话
- **并发支持**：Flask threaded 模式，多用户同时请求
- **前端界面**：会话列表、模式切换、加载状态显示

### Agentic RAG 核心能力
- **知识库检索**：向量检索 + BM25 + Rerank
- **网络搜索**：知识库不足时自动搜索（可选，需配置 SERPER_API_KEY）
- **Agent 决策**：动态决定检索、改写、分解等操作
- **多源融合**：智能处理知识库和网络内容

### 基础功能
- 支持多种文档格式：PDF、Word(.docx)、Excel(.xlsx)、TXT
- 本地向量模型：BGE-base-zh-v1.5
- 本地向量数据库：Chroma
- 精确元数据记录：页码、章节、表格、行列号等
- 增量更新：无需每次完全重建

## 项目结构

```
RAG_damo/
├── models/                    # 模型目录（需下载）
│   ├── bge-base-zh-v1.5/     # 向量模型（必需）
│   │   ├── config.json
│   │   ├── pytorch_model.bin
│   │   ├── tokenizer.json
│   │   └── vocab.txt
│   └── bge-reranker-base/    # 重排序模型（首次运行自动下载）
├── documents/                 # 文档目录
├── chroma_db/                 # 向量数据库（自动生成）
├── chat-ui/                   # 前端界面
│   ├── index.html
│   ├── style.css
│   └── app.js
├── docs/                      # 文档
├── rag_demo.py               # RAG基础功能
├── agentic_rag.py            # Agentic RAG 核心
├── rag_api_server.py         # REST API 服务
├── session_manager.py        # 会话管理器
├── config.example.py         # 配置示例
├── venv/                     # Python虚拟环境
└── README.md
```

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/lacerate551-dev/RAG_damo.git
cd RAG_damo
```

### 2. 创建虚拟环境

```bash
python -m venv venv

# Windows PowerShell
venv\Scripts\activate

# Windows Git Bash
source venv/Scripts/activate

# Linux/macOS
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install chromadb sentence-transformers openai python-docx pdfplumber openpyxl flask flask-cors rank_bm25 jieba requests transformers -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 下载模型

本项目使用两个模型：

| 模型 | 用途 | 大小 | 是否必需 |
|------|------|------|----------|
| BGE-base-zh-v1.5 | 向量编码 | ~400MB | **必需** |
| BGE-reranker-base | 结果重排序 | ~280MB | 可选（首次运行自动下载） |

#### 4.1 下载向量模型（必需）

创建模型目录并下载：

```bash
# 创建模型目录
mkdir models

# 方法1：使用 huggingface-cli（推荐）
pip install huggingface-hub
huggingface-cli download BAAI/bge-base-zh-v1.5 --local-dir ./models/bge-base-zh-v1.5

# 方法2：手动下载
# 访问 https://huggingface.co/BAAI/bge-base-zh-v1.5
# 下载所有文件到 ./models/bge-base-zh-v1.5/ 目录
```

下载完成后，目录结构应为：
```
models/bge-base-zh-v1.5/
├── config.json
├── pytorch_model.bin
├── tokenizer.json
├── tokenizer_config.json
├── vocab.txt
├── special_tokens_map.json
└── ...
```

#### 4.2 重排序模型（可选）

首次运行时会自动下载到 `./models/bge-reranker-base/`，无需手动操作。

如需手动下载：
```bash
huggingface-cli download BAAI/bge-reranker-base --local-dir ./models/bge-reranker-base
```

如不需要重排序功能，可在 `rag_demo.py` 中禁用：
```python
USE_RERANK = False
```

### 5. 配置API密钥

```bash
# 复制配置示例
cp config.example.py config.py

# 编辑 config.py，填入你的 API Key
```

配置文件内容：
```python
# 通义千问API配置（必需）
DASHSCOPE_API_KEY = "your-dashscope-api-key"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_MODEL = "qwen3.5-plus"

# Serper API（可选，用于网络搜索）
SERPER_API_KEY = "your-serper-api-key"

# Dify工作流API配置（可选，用于智能出题）
DIFY_API_URL = "https://api.dify.ai/v1"
DIFY_QUESTION_API_KEY = "your-dify-question-api-key"
DIFY_GRADE_API_KEY = "your-dify-grade-api-key"

# 兼容旧变量名
API_KEY = DASHSCOPE_API_KEY
BASE_URL = DASHSCOPE_BASE_URL
MODEL = DASHSCOPE_MODEL
```

### 6. 准备知识库文档

将文档放入 `documents/` 目录：

```bash
mkdir documents
# 复制你的文档到 documents/ 目录
# 支持 PDF、Word(.docx)、Excel(.xlsx)、TXT 格式
```

### 7. 构建知识库

```bash
# 首次构建或完全重建
python rag_demo.py --rebuild

# 增量同步（添加新文档后）
python rag_demo.py --sync
```

### 8. 启动服务

```bash
# 启动 API 服务
python rag_api_server.py
```

服务启动后：
- API 地址：http://localhost:5001
- 前端页面：打开 `chat-ui/index.html`

## 使用方法

### 双模式对话

| 模式 | 端点 | 模型 | 特点 |
|------|------|------|------|
| 普通聊天 | `/chat` | qwen3.5-flash | 快速响应，日常对话 |
| 知识库问答 | `/rag` | qwen3.5-plus | 检索知识库，准确回答 |

前端界面可点击按钮切换模式。

### API 接口

#### 发送消息

```bash
# 普通聊天
curl -X POST http://localhost:5001/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user1", "session_id": null, "message": "你好"}'

# 知识库问答
curl -X POST http://localhost:5001/rag \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user1", "session_id": null, "message": "请假流程是什么"}'
```

#### 获取会话列表

```bash
curl "http://localhost:5001/sessions?user_id=user1"
```

#### 获取会话历史

```bash
curl "http://localhost:5001/history/{session_id}?user_id=user1"
```

#### 删除会话

```bash
curl -X DELETE "http://localhost:5001/session/{session_id}?user_id=user1"
```

### 命令行问答

```bash
# 单次问答
python rag_demo.py "请假流程是什么"

# 交互模式
python agentic_rag.py
```

交互模式命令：

| 命令 | 说明 |
|------|------|
| `/quit` | 退出程序 |
| `/kb 问题` | 仅知识库检索 |
| `/web 问题` | 强制网络搜索 |
| `/compare 问题` | 对比传统RAG和Agentic RAG |

## 文档管理

### 添加文档

```bash
# 1. 将文档放入 documents/ 目录
# 2. 运行同步
python rag_demo.py --sync
```

### 删除文档

```bash
# 1. 从 documents/ 目录删除文件
# 2. 运行同步
python rag_demo.py --sync
```

## 常见问题

### Q: 向量模型加载失败？

确保 `bge-base-zh-v1.5/` 目录包含以下文件：
- `config.json`
- `pytorch_model.bin`
- `tokenizer.json`
- `vocab.txt`

### Q: Rerank 模型下载慢或失败？

Rerank 模型 (`BAAI/bge-reranker-base`) 会在首次运行时自动从 HuggingFace 下载。

如果下载失败，可以：
1. 使用代理或科学上网
2. 手动下载后放入 `~/.cache/huggingface/hub/` 目录
3. 或在 `rag_demo.py` 中禁用 Rerank：
   ```python
   USE_RERANK = False  # 设置为 False
   ```

### Q: API 调用失败？

1. 检查 `config.py` 是否正确配置 API Key
2. 确认 API Key 有效且未过期
3. 检查网络连接

### Q: 知识库为空？

```bash
# 重新构建知识库
python rag_demo.py --rebuild
```

### Q: 如何查看已索引的文档？

```bash
python rag_demo.py --list
```

### Q: 前端页面无法连接 API？

1. 确认 API 服务已启动：`python rag_api_server.py`
2. 检查端口 5001 是否被占用
3. 确认浏览器访问 http://localhost:5001/health 返回正常

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                      前端 (chat-ui)                          │
│              HTML + CSS + JavaScript                         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    rag_api_server.py                         │
│  ┌─────────────┐              ┌─────────────────────┐       │
│  │  /chat      │              │     /rag            │       │
│  │ 普通聊天     │              │   知识库问答         │       │
│  │ qwen-flash  │              │   qwen-plus         │       │
│  └─────────────┘              └──────────┬──────────┘       │
│                                          │                  │
└──────────────────────────────────────────┼──────────────────┘
                                           │
                          ▼                │
┌─────────────────────────────────────────────────────────────┐
│                    agentic_rag.py                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Agent决策   │  │ 知识库检索   │  │    网络搜索(可选)   │ │
│  │ 检索/改写/  │  │ 向量+BM25+  │  │    Serper API       │ │
│  │ 分解/回答   │  │ Rerank      │  │                     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    rag_demo.py                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ 文档解析     │  │ BGE Embedding│  │     Chroma         │ │
│  │ PDF/Word/   │  │  (本地模型)  │  │   向量数据库        │ │
│  │ Excel/TXT   │  └─────────────┘  └─────────────────────┘ │
│  └─────────────┘                                             │
└─────────────────────────────────────────────────────────────┘
```

## 依赖库

| 库名 | 用途 |
|------|------|
| chromadb | 向量数据库 |
| sentence-transformers | 向量模型 |
| openai | 大模型API |
| pdfplumber | PDF解析 |
| python-docx | Word解析 |
| openpyxl | Excel解析 |
| flask | API服务 |
| flask-cors | 跨域支持 |
| rank_bm25 | BM25检索 |
| jieba | 中文分词 |
| requests | HTTP请求 |

## 版本历史

| 版本 | 更新内容 |
|------|----------|
| v3.0.0 | 双模式RAG系统：普通聊天/知识库问答，会话管理，前端界面 |
| v2.1.0 | 添加Dify智能出题系统集成，支持自动出题和批阅 |
| v1.1.0 | RAG幻觉问题优化（混合检索+Rerank+置信度） |
| v1.0.0 | 初始版本：RAG本地知识库问答系统 |

## License

MIT
