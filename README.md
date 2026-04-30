# RAG Agent - 模块化知识库问答系统

基于本地向量模型 + Chroma向量数据库 + Neo4j知识图谱 + Qwen API 的智能知识库问答系统，支持双模式对话、Agentic RAG 和 Graph RAG。

> **最新版本**: v6.3.0 (状态码系统：统一 API 响应格式、MMR 去重优化、查询扩展增强)

## 功能特性

### 最新特性 (v6.3.0)
- **状态码系统**：统一 API 响应格式，新增 `status_code` 字段便于后端判断处理状态（10xx 处理中、20xx 成功、40xx 客户端错误、50xx 服务端错误）
- **MMR 去重优化**：支持高精度版（语义向量）和轻量版（文本相似度）双模式切换
- **查询扩展增强**：新增查询扩展器、语义缓存、意图分析器
- **部署稳定性**：Gunicorn gthread 模式修复心跳超时问题，Docker shm_size 优化

### v6.2.0 特性
- **Docker 部署方案**：新增完整 Docker 部署配置（Dockerfile、docker-compose、nginx）
- **会话管理重构**：引入 Repository 模式，支持无状态/SQLite 双模式会话存储
- **查询增强优化**：新增自适应 TopK、查询分解器、缓存层、LLM 预算管理
- **配置管理优化**：配置文件模板化（config.example.py、mineru.json.template、.env.production）
- **文档完善**：新增 API 对接规范、MinerU 部署指南、企业文档更新方案

### v6.0.0 特性
- **模块化架构重构**：代码从单文件拆分为清晰的模块结构，提升可维护性
  - `core/` 核心引擎：查询分类、质量评估、置信度门控、推理反思、循环防护
  - `api/` 路由模块：11 个独立路由文件，职责单一
  - `parsers/` 文档解析：支持 PDF/Word/Excel/TXT/图片提取
  - `knowledge/` 知识库管理：多向量库、同步、生命周期
  - `services/` 业务服务：会话、反馈、审计、纲要
  - `auth/` 认证安全：网关认证、输入输出安全
  - `exam_pkg/` 考试系统：出题、批卷、分析
- **图片提取功能**：新增 `image_extractor.py`，支持从文档中提取图片
- **前端界面优化**：chat-ui 样式更新，交互体验提升
- **新增统一入口**：`main.py` 作为推荐启动入口

### v5.0.0 特性
- **多向量库与细粒度权限控制**：全面重构向量库底层，基于公共知识库(`public_kb`)和各部门隔离的子知识库(`dept_xxx`)实现物理阻断，通过网关注入进行 Role/Department 鉴权
- **文档生命周期与版本差异引擎**：引入文档全生命周期跟踪和 MD5 哈希监控差异引擎，文档废止或更新时自动分析关联考题的连带影响
- **本地化自治出题与批卷系统**：建立独立的本地出卷、题库存储系统与题库分析系统，支持脱离工作流进行溯源追踪与本地打分
- **问答质量闭环与纲要生成**：支持记录用户点赞/点踩动作与追问形成本地 FAQ 闭环；使用大模型自动化提取文档大纲及关联推荐
- **全新解析与分块器**：集成结构化 PDF 解析(ODL解析)与 Excel 深度解析扩展，引入智能语义切块算法提升检索精准度

### v4.x 特性
- **v4.2.0**: 出题系统完善，试卷生成/审核/批阅完整流程
- **v4.1.0**: 前端日志面板，实时显示 Agent 思考过程
- **v4.0.0**: Graph RAG，Neo4j 图数据库存储实体关系，多跳推理查询

### Agentic RAG 核心能力
- **知识库检索**：向量检索 + BM25 + Rerank
- **网络搜索**：实时信息自动搜索（需配置 SERPER_API_KEY）
- **图谱检索**：实体关系推理、多跳查询
- **Agent 决策**：动态决定检索、改写、分解等操作
- **多源融合**：智能处理知识库、网络、图谱内容

### 基础功能
- 支持多种文档格式：PDF、Word(.docx)、Excel(.xlsx)、TXT、图片提取
- 本地向量模型：BGE-base-zh-v1.5
- 本地向量数据库：Chroma
- 精确元数据记录：页码、章节、表格、行列号等
- 增量更新：无需每次完全重建

## 项目结构（模块化）

```
rag-agent/
├── main.py                  # ✨ 统一启动入口（推荐）
├── config.py                # API 配置（需自行创建）
├── config.example.py        # API 配置模板
├── requirements.txt         # 依赖列表
│
├── core/                    # RAG 核心引擎
│   ├── agentic.py           #   Agentic RAG 智能问答引擎
│   ├── engine.py            #   检索引擎核心
│   ├── bm25_index.py        #   BM25 关键词检索
│   ├── chunker.py           #   语义分块器
│   ├── query_classifier.py  #   查询分类器
│   ├── quality_assessor.py  #   质量评估器
│   ├── confidence_gate.py   #   置信度门控
│   ├── reasoning_reflector.py #   推理反思器
│   └── loop_guard.py        #   循环防护器
│
├── parsers/                 # 文档解析器
│   ├── mineru_parser.py      #   MinerU 统一解析（PDF/DOCX/PPTX/图片）
│   ├── pdf_mineru.py         #   MinerU PDF 兼容别名
│   ├── excel_parser.py       #   Excel 解析（Pandas 管道）
│   ├── txt_parser.py         #   TXT 文本解析
│   └── image_extractor.py   #   图片提取器
│
├── knowledge/               # 知识库管理
│   ├── manager.py           #   多向量库管理器
│   ├── router.py            #   知识库路由器
│   ├── sync.py              #   同步服务
│   ├── lifecycle.py         #   文档生命周期
│   ├── diff.py              #   文档差异分析
│   └── vector_store/        #   向量存储目录
│
├── exam_pkg/                # 考试系统
│   ├── manager.py           #   出题与批卷管理
│   ├── api.py               #   Flask Blueprint
│   ├── analysis.py          #   考试分析
│   ├── local_db.py          #   本地题库
│   └── question_hook.py     #   题目维护钩子
│
├── services/                # 业务服务
│   ├── session.py           #   会话管理
│   ├── audit.py             #   审计日志
│   ├── feedback.py          #   反馈质量闭环
│   ├── outline.py           #   纲要生成与推荐
│   └── user_info.py         #   用户信息服务
│
├── auth/                    # 认证与安全
│   ├── gateway.py           #   网关认证
│   └── security.py          #   输入/输出安全
│
├── api/                     # API 路由层
│   ├── __init__.py          #   Flask 应用工厂
│   ├── chat_routes.py       #   聊天路由
│   ├── document_routes.py   #   文档管理路由
│   ├── kb_routes.py         #   知识库路由
│   ├── sync_routes.py       #   同步路由
│   ├── session_routes.py    #   会话路由
│   ├── feedback_routes.py   #   反馈路由
│   ├── outline_routes.py    #   纲要路由
│   ├── question_routes.py   #   题目路由
│   ├── audit_routes.py      #   审计路由
│   ├── graph_routes.py      #   图谱路由
│   ├── image_routes.py      #   图片路由
│   └── auth_routes.py       #   认证路由
│
├── graph/                   # 知识图谱
├── scripts/                 # 工具脚本
├── models/                  # 本地模型目录
├── documents/               # 知识库文档目录
├── data/                    # SQLite 数据库
├── chat-ui/                 # 前端界面
├── tests/                   # 测试
├── docs/                    # 文档
├── venv/                    # 虚拟环境
│
├── rag_api_server.py        # ⚠️ 旧入口（兼容层）
└── rag_demo.py              # ⚠️ 旧入口（兼容层）
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
# 激活虚拟环境后运行
python rag_demo.py --rebuild

# 构建知识图谱（需要 Neo4j）
python graph_build.py
```

### 9. 启动服务

```bash
# ✨ 推荐方式 - 新入口
python main.py                  # 启动 API 服务（端口 5001）
python main.py --port 8080      # 指定端口

# 旧入口（仍可用）
python rag_api_server.py        # 启动 API 服务
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
python -c "from core.agentic import AgenticRAG; rag = AgenticRAG(); print(rag.query('请假流程是什么'))"

# 交互模式
python rag_demo.py

# 单次问答
python rag_demo.py "请假流程是什么"
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
│                           API 路由层 (api/)                              │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│   │ chat_routes │    │ kb_routes   │    │   graph_routes          │    │
│   │   /chat     │    │   /kb       │    │   /graph/*              │    │
│   └──────┬──────┘    └──────┬──────┘    └───────────┬─────────────┘    │
└──────────┼──────────────────┼───────────────────────┼───────────────────┘
           │                  │                       │
           ▼                  ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        核心引擎层 (core/)                                 │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│   │ agentic.py  │    │ engine.py   │    │   Graph RAG             │    │
│   │ Agent决策   │    │ 检索引擎     │    │   实体提取 + 图谱查询    │    │
│   └─────────────┘    └─────────────┘    └─────────────────────────┘    │
│                                                                          │
│   ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────────────┐  │
│   │ query_    │ │ quality_  │ │confidence_│ │ reasoning_reflector   │  │
│   │ classifier│ │ assessor  │ │   gate    │ │   推理反思器           │  │
│   └───────────┘ └───────────┘ └───────────┘ └───────────────────────┘  │
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
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    文档解析器 (parsers/)                          │   │
│   │          PDF / Word / Excel / TXT / 图片提取                     │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
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

### 文档管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/documents/upload` | POST | 上传文件到知识库 |
| `/documents/list` | GET | 获取文档列表 |
| `/documents/<path>` | DELETE | 删除文档 |

详细 API 文档请参考 [API接口文档](docs/API接口文档.md)

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
| **v6.3.0** | 状态码系统：统一 API 响应格式(status_code)、MMR 双模式去重、查询扩展增强、Gunicorn gthread 稳定性修复 |
| v6.2.0 | 部署优化版：Docker 部署方案、会话管理 Repository 重构、查询增强（自适应TopK/分解器/缓存）、配置模板化 |
| v6.1.0 | 部署准备版：表格摘要懒加载优化、MinerU解析器统一、出题系统增强、新增后端对接规范文档 |
| v6.0.0 | 模块化架构重构：代码拆分为 core/api/parsers/knowledge/services/auth/exam_pkg 模块；新增图片提取功能；前端优化；统一入口 main.py |
| v5.0.0 | 多向量库权限控制、文档生命周期、本地出卷系统、ODL解析、Semantic Chunker |
| v4.2.0 | 出题系统完善：试卷审核流程优化、前端界面修复 |
| v4.1.0 | 前端日志面板：实时显示 Agent 思考过程，日志持久化 |
| v4.0.0 | Graph RAG：Neo4j 知识图谱、实体提取、多跳推理 |
| v3.0.0 | 双模式 RAG 系统：普通聊天/知识库问答，会话管理 |
| v2.1.0 | Dify 智能出题系统集成 |
| v1.1.0 | RAG 幻觉优化：混合检索 + Rerank + 置信度 |
| v1.0.0 | 初始版本：RAG 本地知识库问答系统 |

## 文档

- [API接口文档](docs/API接口文档.md) - 完整 API 接口说明、认证、出题系统
- [开发文档](docs/开发文档.md) - 系统架构、技术栈、部署指南
- [模块说明](docs/模块说明.md) - 各模块职责与接口
- [数据库设计文档](docs/数据库设计文档.md) - 数据库表结构设计
- [多向量库实现权限划分](docs/多向量库实现权限划分.md) - 权限系统技术说明
- [多源信息融合指南](docs/多源信息融合指南.md) - 知识库与网络搜索融合策略

## License

MIT
