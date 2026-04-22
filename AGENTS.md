# RAG 知识库服务

## 项目定位

RAG 服务负责：
- **向量存储**：ChromaDB 向量数据库管理
- **关键词检索**：BM25 索引
- **文档解析**：PDF/Word/Excel 解析与分块
- **知识库问答**：Agentic RAG 问答引擎
- **同步服务**：文档变更检测与向量化

后端服务负责：
- 用户认证与权限控制
- 会话管理与对话历史
- 审计日志与反馈记录
- 业务数据存储

## 虚拟环境 (重要)

本项目虚拟环境目录为 `venv/`，运行 Python 脚本时**必须**使用虚拟环境。

### Codex 中运行脚本

```bash
# 正确方式 - 使用完整路径
"C:/Users/qq318/Desktop/rag-agent/venv/Scripts/python.exe" "C:/Users/qq318/Desktop/rag-agent/脚本名.py"
```

### 用户在 PowerShell 中运行

```powershell
# 方式1: 激活虚拟环境后运行
.\venv\Scripts\Activate.ps1
python main.py

# 方式2: 直接使用虚拟环境 Python
.\venv\Scripts\python.exe main.py
```

## 项目结构

```
├── main.py                  # 统一启动入口
├── config.py                # API 配置（需自行创建）
├── requirements.txt         # 依赖列表
│
├── core/                    # RAG 核心引擎
│   ├── agentic.py           #   AgenticRAG 智能问答
│   ├── bm25_index.py        #   BM25 关键词检索
│   ├── chunker.py           #   语义分块器
│   └── engine.py            #   基础检索引擎
│
├── parsers/                 # 文档解析器
│   ├── pdf_odl.py           #   PDF 解析
│   ├── docx_docling.py      #   Word 解析
│   └── excel_parser.py      #   Excel 解析
│
├── knowledge/               # 知识库管理
│   ├── manager.py           #   向量库管理器
│   ├── router.py            #   知识库路由
│   └── sync.py              #   同步服务
│
├── exam_pkg/                # 出题系统（无状态）
│   ├── manager.py           #   题目生成逻辑
│   └── api.py               #   出题接口
│
├── auth/                    # 认证
│   ├── gateway.py           #   Header 读取
│   └── security.py          #   输入/输出安全
│
├── api/                     # API 路由层
│   ├── __init__.py          #   create_app() 工厂
│   ├── chat_routes.py       #   问答接口
│   ├── kb_routes.py         #   向量库管理
│   ├── document_routes.py   #   文档管理
│   └── sync_routes.py       #   同步服务
│
├── documents/               # 知识库文档目录
├── vector_store/            # 向量数据库 (ChromaDB)
├── chat-ui/                 # 前端界面
└── venv/                    # 虚拟环境
```

## 快速启动

```powershell
# 安装依赖
.\venv\Scripts\pip install -r requirements.txt

# 启动服务
python main.py                  # 端口 5001
python main.py --port 8080      # 指定端口
```

## 开发模式

设置环境变量 `DEV_MODE=true`（默认开启）时：
- 支持模拟用户：`Authorization: Bearer mock-token-admin`
- 无需后端网关注入 Header
- 所有核心功能可本地测试

## API 接口概览

### 问答接口
- `POST /chat` - 普通聊天
- `POST /rag` - 知识库问答
- `POST /rag/stream` - 流式问答
- `POST /search` - 混合检索

### 向量库管理
- `GET /collections` - 向量库列表
- `POST /collections` - 创建向量库
- `PUT /collections/<name>` - 修改向量库
- `DELETE /collections/<name>` - 删除向量库

### 文档管理
- `POST /documents/upload` - 上传文件
- `POST /documents/batch-upload` - 批量上传
- `GET /documents/list` - 文档列表
- `DELETE /documents/<path>` - 删除文档

### 切片管理
- `GET /documents/<path>/chunks` - 查看文件切片
- `POST /chunks` - 新增切片
- `PUT /chunks/<id>` - 修改切片
- `DELETE /chunks/<id>` - 删除切片

### 同步服务
- `POST /sync` - 触发同步
- `GET /sync/status` - 同步状态

### 出题接口
- `POST /exam/generate` - 生成题目
- `POST /exam/grade` - 批改答案
