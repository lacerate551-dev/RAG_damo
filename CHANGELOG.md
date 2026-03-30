# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - Graph RAG
- **知识图谱模块** - Neo4j 图数据库集成
  - `graph_manager.py`: 图谱管理器，支持实体/关系的 CRUD 操作
  - `entity_extractor.py`: LLM 驱动的实体提取器
  - `graph_rag.py`: 图谱增强检索模块
  - `graph_build.py`: 图谱构建脚本

- **Graph RAG 功能**
  - 向量检索 + 图谱检索融合
  - 多跳推理查询（如"XX部门负责什么制度"）
  - 实体关系自动发现
  - 中文关系类型映射（负责→RESPONSIBLE_FOR）

- **前端图谱状态显示**
  - 图谱连接状态面板
  - 节点/关系数量统计
  - 实体类型分布展示
  - "测试图谱检索"按钮

- **Graph RAG API**
  - `POST /graph/search`: 图谱检索接口
  - `POST /graph/build`: 重建图谱索引
  - `GET /graph/stats`: 获取图谱统计信息

- **智能聊天网络搜索**
  - Chat 模式支持网络搜索（实时天气、新闻等）
  - 自动判断是否需要实时信息
  - 触发关键词：今天、最新、天气、新闻、股价等
  - 消息显示"网络搜索"标签

### Changed
- `/chat` 接口从直接 LLM 调用改为 `agentic_rag.chat_search()`
- 前端模式命名："普通聊天" → "智能聊天"
- 返回结果增加 `web_searched` 字段

### Technical Details - Graph RAG

| 组件 | 技术 | 说明 |
|------|------|------|
| 图数据库 | Neo4j 5.x | Docker 部署 |
| 实体提取 | LLM (Qwen) | 从文档自动提取三元组 |
| 关系映射 | 中文→英文 | Neo4j 关系类型限制 |
| 检索融合 | Vector + Graph | 上下文融合生成答案 |

---

## [3.0.0] - 2025-03-28

### Added
- **双模式对话系统**
  - `/chat`: 普通聊天模式 (qwen3.5-flash)
  - `/rag`: 知识库问答模式 (qwen3.5-plus)

- **会话管理**
  - SQLite 持久化存储
  - 多用户多会话支持
  - 会话列表、历史记录、删除功能

- **前端界面**
  - `chat-ui/`: HTML + CSS + JavaScript
  - 会话列表侧边栏
  - 模式切换按钮
  - 加载状态显示
  - 来源信息展示

- **并发支持**
  - Flask threaded 模式
  - 多用户同时请求

- **Agentic RAG**
  - Agent 决策：动态决定检索、改写、分解
  - 网络搜索：Serper API 集成
  - 多源融合：知识库 + 网络内容

### Changed (v3.0.0 后的优化提交)
- 统一模型目录管理，使用 HuggingFace 模型名
- 合并 rag_api.py 到 rag_api_server.py
- 增量同步时同步更新 BM25 索引
- 从 rag_demo.py 移除图谱构建代码

### Technical Details

| 模块 | 技术 | 说明 |
|------|------|------|
| 会话管理 | SQLite | sessions.db |
| 前端 | Vanilla JS | 无框架依赖 |
| API | Flask + CORS | 跨域支持 |

---

## [2.1.0] - 2025-03-27

### Added
- Dify 智能出题系统集成
- 自动出题和批阅功能
- `exam_manager.py`: 出题系统管理器
- Dify 快速入门指南文档

### Changed
- 更新配置模板支持 Dify API

---

## [1.1.0] - 2025-03-27

### Added
- **P1: Excel智能分块** - Excel数据按语义块存储，解决表格检索碎片化问题
- **P2: 置信度标注** - 回答末尾自动添加置信度评估（高/中/低）
- **P3: Rerank重排序** - 使用CrossEncoder对检索结果精排，提高准确率
- **P4: 混合检索** - 向量检索 + BM25关键词检索 + RRF融合 + Rerank精排
- BM25索引管理器，支持中文分词(jieba)
- RAG幻觉问题优化方案文档

### Changed
- 重构检索模块，支持多种检索策略
- 优化Prompt，添加严格约束防止幻觉

### Technical Details
| 优化项 | 技术 | 效果 |
|--------|------|------|
| P1 | Excel智能分块 | 354片段→4片段，检索完整 |
| P2 | Prompt优化 | 置信度标注 |
| P3 | bge-reranker-base | 精确打分 |
| P4 | BM25 + RRF + Rerank | 语义+关键词融合 |

---

## [1.0.0] - 2025-03-26

### Added
- 初始版本：RAG本地知识库问答系统
- 支持PDF、Word、Excel、TXT格式
- 本地向量模型 bge-base-zh-v1.5
- Chroma向量数据库
- Qwen3.5-plus API调用
