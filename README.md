# RAG Demo - 本地知识库问答系统

基于本地向量模型 + Chroma向量数据库 + Neo4j知识图谱 + Qwen API 的智能知识库问答系统，支持双模式对话、Agentic RAG 和 Graph RAG。

> **最新版本**: v4.2.0 (出题系统完善 + 审核流程优化)

## 功能特性

### 最新特性 (v4.2.0)
- **出题系统完善**：试卷生成、审核、批阅完整流程
- **审核流程优化**：管理员可在"审核试卷"中审核草稿试卷
- **前端界面优化**：修复页面滚动问题，优化交互体验
- **试卷名称自定义**：生成试卷时可指定名称

### v4.1.0 特性
- **前端日志面板**：实时显示Agent思考过程（决策、检索、改写、回答等）
- **日志持久化**：localStorage存储，刷新页面后日志保留
- **来源去重**：同一来源合并显示，页码信息整合

### v4.0.0 特性
- **Graph RAG**：Neo4j 图数据库存储实体关系，多跳推理查询
- **图谱检索**：向量检索 + 图谱检索融合
- **智能聊天网络搜索**：Chat 模式支持实时天气、新闻查询
- **双模式切换**：智能聊天(支持网络搜索) / 知识库问答(多源检索)
- **出题系统**：Dify 智能出题 + 批阅 + 前端管理界面

### Agentic RAG 核心能力
- **知识库检索**：向量检索 + BM25 + Rerank
- **网络搜索**：实时信息自动搜索（需配置 SERPER_API_KEY）
- **图谱检索**：实体关系推理、多跳查询
- **Agent 决策**：动态决定检索、改写、分解等操作
- **多源融合**：智能处理知识库、网络、图谱内容

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
│   └── bge-reranker-base/    # 重排序模型（自动下载）
├── documents/                 # 文档目录
├── 题库/                      # 试卷存储目录
├── 批阅报告/                   # 批阅报告目录
├── chroma_db/                 # 向量数据库（自动生成）
├── chat-ui/                   # 前端界面
│   ├── index.html            # 主聊天界面
│   ├── exam.html             # 出题系统界面
│   ├── style.css
│   ├── app.js
│   └── exam.js
├── docs/                      # 文档
├── rag_demo.py               # RAG基础功能
├── agentic_rag.py            # Agentic RAG 核心
├── graph_rag.py              # Graph RAG 检索模块
├── graph_manager.py          # Neo4j 图谱管理器
├── entity_extractor.py       # 实体提取器
├── graph_build.py            # 图谱构建脚本
├── rag_api_server.py         # REST API 服务
├── exam_manager.py           # 出题系统核心逻辑
├── exam_api.py               # 出题系统 API
├── session_manager.py        # 会话管理器
├── config.example.py         # 配置示例
├── requirements.txt          # Python依赖
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
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

Graph RAG 额外依赖：
```bash
pip install neo4j -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 下载模型

本项目使用两个模型：

| 模型 | 用途 | 大小 | 是否必需 |
|------|------|------|----------|
| BGE-base-zh-v1.5 | 向量编码 | ~400MB | **必需** |
| BGE-reranker-base | 结果重排序 | ~280MB | 可选（首次运行自动下载） |

```bash
# 创建模型目录
mkdir models

# 下载向量模型
huggingface-cli download BAAI/bge-base-zh-v1.5 --local-dir ./models/bge-base-zh-v1.5
```

### 5. 配置API密钥

```bash
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

# Neo4j 图数据库配置（可选，用于 Graph RAG）
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"
USE_GRAPH_RAG = True  # 是否启用图谱检索

# 兼容旧变量名
API_KEY = DASHSCOPE_API_KEY
BASE_URL = DASHSCOPE_BASE_URL
MODEL = DASHSCOPE_MODEL
```

### 6. 启动 Neo4j（可选，用于 Graph RAG）

```bash
# 使用 Docker 启动 Neo4j
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -v neo4j_data:/data \
  neo4j:latest

# 访问 Neo4j Browser: http://localhost:7474
```

### 7. 准备知识库文档

将文档放入 `documents/` 目录，支持 PDF、Word(.docx)、Excel(.xlsx)、TXT 格式。

### 8. 构建知识库

```bash
# 构建向量索引 + BM25索引
python rag_demo.py --rebuild

# 构建知识图谱（需要 Neo4j）
python graph_build.py
```

### 9. 启动服务

```bash
python rag_api_server.py
```

服务启动后：
- API 地址：http://localhost:5001
- 前端页面：打开 `chat-ui/index.html`

## 使用方法

### 双模式对话

| 模式 | 端点 | 特点 |
|------|------|------|
| 智能聊天 | `/chat` | 支持网络搜索，适合实时问题（天气、新闻等） |
| 知识库问答 | `/rag` | 知识库 + 网络 + 图谱多源检索，专业准确 |

前端界面可点击按钮切换模式。

### Graph RAG API

```bash
# 图谱检索
curl -X POST http://localhost:5001/graph/search \
  -H "Content-Type: application/json" \
  -d '{"query": "信息技术部负责什么？", "top_k": 5, "depth": 2}'

# 获取图谱统计
curl http://localhost:5001/graph/stats

# 重建图谱索引
curl -X POST http://localhost:5001/graph/build
```

### 命令行问答

```bash
# 知识库问答
python agentic_rag.py "请假流程是什么"

# 交互模式
python agentic_rag.py

# 测试 Graph RAG
python graph_test.py
```

交互模式命令：

| 命令 | 说明 |
|------|------|
| `/quit` | 退出程序 |
| `/kb 问题` | 仅知识库检索 |
| `/web 问题` | 强制网络搜索 |

## 出题系统

### 功能概述

出题系统支持智能生成试卷、审核管理、学生答题和自动批阅。

### 使用流程

```
生成试卷 → 管理员审核 → 学生答题 → 自动批阅 → 生成报告
   (草稿)    (通过/驳回)   (已通过试卷)   (系统评分)
```

### 前端界面

访问 `chat-ui/exam.html` 进入出题系统：

1. **生成试卷**：输入主题、题目数量、难度等参数
2. **审核试卷**：管理员审核草稿试卷（审核通过后才能用于考试）
3. **批阅试卷**：选择已通过的试卷，学生作答后系统自动批阅
4. **批阅报告**：查看历史批阅记录和成绩

### 试卷状态

| 状态 | 说明 |
|------|------|
| `draft` | 草稿，管理员可审核 |
| `approved` | 已通过，可用于学生答题 |
| `rejected` | 已驳回，不可使用 |

### API 调用示例

```bash
# 生成试卷
curl -X POST http://localhost:5001/exam/generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"topic": "Python基础", "choice_count": 5, "name": "Python入门测试"}'

# 审核通过
curl -X POST http://localhost:5001/exam/<exam_id>/review \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'

# 批阅试卷
curl -X POST http://localhost:5001/exam/<exam_id>/grade \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"student_name": "张三", "answers": {"choice_1": "A", "blank_1": "答案"}}'
```

## 技术架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         前端 (chat-ui)                                   │
│                 HTML + CSS + JavaScript                                  │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│   │ 智能聊天     │    │ 知识库问答   │    │     图谱状态显示         │    │
│   │ +网络搜索    │    │ +图谱检索    │    │   节点/关系/类型         │    │
│   └─────────────┘    └─────────────┘    └─────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       rag_api_server.py                                  │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│   │   /chat     │    │    /rag     │    │    /graph/search        │    │
│   │ 智能聊天     │    │  知识库问答  │    │     图谱检索            │    │
│   └──────┬──────┘    └──────┬──────┘    └───────────┬─────────────┘    │
│          │                  │                       │                   │
└──────────┼──────────────────┼───────────────────────┼───────────────────┘
           │                  │                       │
           ▼                  ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Agentic RAG                                       │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│   │ Agent决策   │    │ 知识库检索   │    │     Graph RAG           │    │
│   │ 检索/改写/  │    │ 向量+BM25+  │    │   实体提取 + 图谱查询    │    │
│   │ 分解/回答   │    │ Rerank      │    │                         │    │
│   └─────────────┘    └─────────────┘    └─────────────────────────┘    │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      网络搜索 (Serper API)                       │   │
│   │              实时信息：天气、新闻、股价等                         │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          数据层                                          │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│   │  ChromaDB   │    │   BM25索引   │    │       Neo4j            │    │
│   │  向量数据库  │    │  关键词检索  │    │     知识图谱           │    │
│   └─────────────┘    └─────────────┘    └─────────────────────────┘    │
│                                                                          │
│   ┌─────────────┐    ┌─────────────┐                                    │
│   │ 文档解析     │    │ BGE向量模型  │                                    │
│   │ PDF/Word/   │    │  (本地运行)  │                                    │
│   │ Excel/TXT   │    └─────────────┘                                    │
│   └─────────────┘                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

## Graph RAG 功能详解

### 实体类型

从企业制度文档中自动提取的实体类型：

| 实体类型 | 示例 |
|----------|------|
| 部门 | 人力资源部、财务部、信息技术部 |
| 制度 | 差旅管理办法、信息安全管理制度 |
| 人员 | 员工、经理、审批人 |
| 流程 | 报销流程、审批流程 |
| 条件 | 享受条件、适用范围 |

### 关系类型

| 关系 | 示例 |
|------|------|
| 负责 | 人力资源部 → 负责 → 差旅管理办法 |
| 适用 | 差旅管理办法 → 适用 → 员工 |
| 包含 | 报销流程 → 包含 → 审批步骤 |
| 审批 | 部门负责人 → 审批 → 报销申请 |

### 多跳查询示例

```
Q: 发生一级安全事件后应该向谁报告？
→ 图谱推理链：
  一级安全事件 --属于--> 安全事件
  安全事件 --报告--> 应急响应小组
  应急响应小组 --由--> 安全部门负责
→ A: 应向应急响应小组报告，由安全部门负责处理
```

## API 接口文档

### 基础接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/chat` | POST | 智能聊天（支持网络搜索） |
| `/rag` | POST | 知识库问答（多源检索） |
| `/search` | POST | 混合检索（供 Dify 调用） |
| `/sessions` | GET | 获取会话列表 |
| `/history/<id>` | GET | 获取会话历史 |
| `/session/<id>` | DELETE | 删除会话 |
| `/health` | GET | 健康检查 |

### Graph RAG 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/graph/search` | POST | 图谱检索 |
| `/graph/build` | POST | 重建图谱索引 |
| `/graph/stats` | GET | 获取图谱统计 |

### 出题系统接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/exam/generate` | POST | 生成试卷 |
| `/exam/list` | GET | 获取试卷列表 |
| `/exam/<id>` | GET/PUT/DELETE | 试卷 CRUD |
| `/exam/<id>/review` | POST | 审核试卷（管理员） |
| `/exam/<id>/grade` | POST | 批阅试卷 |
| `/exam/report/<id>` | GET | 获取批阅报告 |
| `/exam/report/list` | GET | 批阅报告列表 |

详细 API 文档请参考 [API对接文档](docs/API对接文档.md)

## 依赖库

| 库名 | 用途 |
|------|------|
| chromadb | 向量数据库 |
| sentence-transformers | 向量模型 |
| openai | 大模型API |
| neo4j | 图数据库 |
| pdfplumber | PDF解析 |
| python-docx | Word解析 |
| openpyxl | Excel解析 |
| flask | API服务 |
| flask-cors | 跨域支持 |
| rank_bm25 | BM25检索 |
| jieba | 中文分词 |
| requests | HTTP请求 |

## 常见问题

### Q: Neo4j 连接失败？

1. 确认 Docker 已启动 Neo4j 容器
2. 访问 http://localhost:7474 检查 Neo4j Browser
3. 检查 config.py 中的 NEO4J_PASSWORD 是否正确

### Q: Graph RAG 未启用？

确保 config.py 中设置：
```python
USE_GRAPH_RAG = True
```

### Q: 网络搜索不工作？

1. 确认 config.py 中配置了 SERPER_API_KEY
2. 注册地址: https://serper.dev/

### Q: 向量模型加载失败？

确保 `models/bge-base-zh-v1.5/` 目录包含必要文件。

## 版本历史

| 版本 | 更新内容 |
|------|----------|
| **v4.2.0** | 出题系统完善：试卷审核流程优化、前端界面修复、试卷名称自定义 |
| **v4.1.0** | 前端日志面板：实时显示Agent思考过程，日志持久化存储；来源去重优化 |
| **v4.0.0** | Graph RAG：Neo4j知识图谱、实体提取、多跳推理；智能聊天网络搜索；出题系统集成 |
| v3.0.0 | 双模式RAG系统：普通聊天/知识库问答，会话管理，前端界面 |
| v2.1.0 | Dify智能出题系统集成 |
| v1.1.0 | RAG幻觉优化：混合检索+Rerank+置信度 |
| v1.0.0 | 初始版本：RAG本地知识库问答系统 |

## 文档

- [API对接文档](docs/API对接文档.md) - 完整 API 接口说明、认证、出题系统
- [开发文档](docs/开发文档.md) - 系统架构、技术栈、Dify 集成、部署指南
- [Graph RAG 使用指南](docs/Graph_RAG使用指南.md) - 知识图谱功能详解
- [Agentic RAG 完整指南](docs/Agentic_RAG完整指南.md) - Agent 决策机制与使用方法
- [Dify 快速入门指南](docs/Dify快速入门指南.md) - Dify 工作流集成教程
- [出题批卷系统集成方案](docs/出题批卷系统集成方案.md) - 出题系统设计文档
- [文档权限控制实现说明](docs/文档权限控制实现说明.md) - 权限系统技术说明
- [多源信息融合指南](docs/多源信息融合指南.md) - 知识库与网络搜索融合策略
- [RAG幻觉问题优化方案](docs/RAG幻觉问题优化方案.md) - 幻觉问题分析与解决方案
- [RAG系统生产环境风险分析](docs/RAG系统生产环境风险分析与优化方向.md) - 安全风险与优化方向

## License

MIT
