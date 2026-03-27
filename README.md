# RAG Demo - 本地知识库问答系统

基于本地向量模型 + Chroma向量数据库 + Qwen API 的简单知识库问答系统，支持Dify智能出题系统集成。

## 功能特性

### 核心功能
- 支持多种文档格式：PDF、Word(.docx)、Excel(.xlsx)、TXT
- 本地向量模型：BGE-base-zh-v1.5
- 本地向量数据库：Chroma
- 大模型API：Qwen3.5-plus
- 精确元数据记录：页码、章节、表格、行列号等
- 增量更新：无需每次完全重建

### 智能出题系统（v2.1.0新增）
- Dify工作流集成：智能出题 + 自动批阅
- 支持题型：选择题、填空题、简答题
- 混合检索：向量检索 + BM25 + RRF融合 + Rerank精排
- 一键生成试卷：根据知识库内容自动出题
- 自动批阅：选择题规则匹配，主观题AI评分

## 项目结构

```
简单智能体入门/
├── bge-base-zh-v1.5/     # 本地向量模型
├── documents/            # 文档目录
├── chroma_db/            # 向量数据库（自动生成）
├── rag_demo.py           # RAG主程序
├── rag_api.py            # RAG API服务（供Dify调用）
├── exam_manager.py       # 智能出题系统管理器
├── config.py             # API配置（需自行创建）
├── config.example.py     # 配置示例
├── docs/
│   └── Dify快速入门指南.md  # Dify工作流配置文档
├── venv/                 # Python虚拟环境
└── README.md
```

## 安装

### 1. 创建虚拟环境

```bash
python -m venv venv
```

### 2. 激活虚拟环境

```bash
# Windows PowerShell
venv\Scripts\activate

# Windows Git Bash
source venv/Scripts/activate

# Linux/macOS
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install chromadb sentence-transformers openai python-docx pdfplumber openpyxl flask flask-cors rank_bm25 jieba -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 配置API密钥

```bash
# 复制配置示例
cp config.example.py config.py

# 编辑config.py，填入你的API密钥
```

配置文件内容：
```python
# 通义千问API配置
DASHSCOPE_API_KEY = "your-dashscope-api-key"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_MODEL = "qwen3.5-plus"

# Dify工作流API配置（智能出题系统）
DIFY_API_URL = "https://api.dify.ai/v1"
DIFY_QUESTION_API_KEY = "your-dify-question-api-key"  # 出题工作流
DIFY_GRADE_API_KEY = "your-dify-grade-api-key"        # 批阅工作流
```

## 使用方法

### RAG问答系统

#### 命令行模式

```bash
# 直接提问（单次问答）
python rag_demo.py "学生请假有哪些注意事项？"

# 列出已索引的文件
python rag_demo.py --list

# 增量同步文档（自动检测新增/删除的文件）
python rag_demo.py --sync

# 完全重建知识库
python rag_demo.py --rebuild
```

#### 交互模式

```bash
python rag_demo.py
```

#### RAG API服务（供Dify调用）

```bash
# 启动API服务
python rag_api.py

# 服务地址
http://localhost:5000/search
```

### 智能出题系统

#### 生成试卷

```python
from exam_manager import generate_exam, save_exam

# 生成试卷
exam = generate_exam(
    topic="科研项目管理",
    choice_count=3,      # 选择题数量
    blank_count=2,       # 填空题数量
    short_answer_count=2, # 简答题数量
    difficulty=3         # 难度(1-5)
)

# 保存到题库
save_exam(exam, "test1")
# 保存到: 题库/test1.json
```

#### 批阅试卷

```python
from exam_manager import grade_exam, save_grade_report

# 学生答案
student_answers = {
    "choice_1": "A",
    "choice_2": "B",
    "blank_1": "答案内容",
    "short_answer_1": "学生作答..."
}

# 批阅
report = grade_exam("./题库/test1.json", student_answers)

# 保存报告
save_grade_report(report, "张三")
# 保存到: 批阅报告/张三_20240101.json
```

详细配置请参考 [Dify快速入门指南](docs/Dify快速入门指南.md)

进入交互模式后，可使用以下命令（以 `/` 开头）：

| 命令 | 说明 | 示例 |
|------|------|------|
| `/quit` | 退出程序 | `/quit` |
| `/rebuild` | 完全重建知识库 | `/rebuild` |
| `/sync` | 同步文档（增量更新） | `/sync` |
| `/add <文件名>` | 添加单个文件 | `/add 新文档.pdf` |
| `/del <文件名>` | 删除单个文件 | `/del 旧文档.docx` |
| `/list` | 列出已索引的文件 | `/list` |
| `/help` | 显示帮助信息 | `/help` |
| 其他内容 | 作为问题进行问答 | `请假需要提前几天？` |

**注意：** 命令以 `/` 开头，不带 `/` 的输入会被当作问题处理。例如输入 `list` 会查询包含 "list" 的内容，而 `/list` 才是列出文件的命令。

### 交互模式示例

```
==================================================
知识库问答
==================================================
命令 (以 / 开头):
  /quit    - 退出程序
  /rebuild - 完全重建知识库
  /sync    - 同步文档（增量更新）
  /add <文件名> - 添加单个文件
  /del <文件名> - 删除单个文件
  /list    - 列出已索引的文件
  /help    - 显示帮助信息
其他输入将作为问题进行问答
==================================================

------------------------------

请输入问题或命令: 学生请假有哪些注意事项？

[检索中...]
找到 3 个相关片段
涉及文档: 南京工业职业技术学院工作制度汇编.pdf

[生成回答中...]

==================================================
回答:
------------------------------
根据参考资料《南京工业职业技术学院工作制度汇编.pdf》，学生请假的注意事项如下：

1. 办理时间与方式...
------------------------------

参考片段:
  [1] 南京工业职业技术学院工作制度汇编.pdf 第15页 【学生请假管理规定】: 生如果需要外出...
  [2] 南京工业职业技术学院工作制度汇编.pdf 第16页: 先办理缓考手续...
  [3] 南京工业职业技术学院工作制度汇编.pdf 第14页: 有效证明...
```

## 文档管理

### 添加文档

1. 将文档放入 `documents/` 文件夹
2. 运行同步命令：

```bash
# 方法1：交互模式
> /sync

# 方法2：交互模式添加单个文件
> /add 新文档.pdf

# 方法3：命令行
python rag_demo.py --sync
```

### 删除文档

1. 从 `documents/` 文件夹删除文件
2. 运行同步命令：

```bash
# 方法1：交互模式
> /sync

# 方法2：交互模式删除单个文件
> /del 旧文档.docx

# 方法3：命令行
python rag_demo.py --sync
```

### 增量更新 vs 完全重建

| 操作 | 增量更新 | 完全重建 |
|------|----------|----------|
| 新增文件 | 只处理新文件 | 处理所有文件 |
| 删除文件 | 只删除该文件数据 | 全部删除再重建 |
| 修改文件 | 删除旧数据+添加新数据 | 全部重建 |
| 耗时 | 秒级 | 分钟级 |
| 命令 | `/sync` / `/add` / `/del` | `/rebuild` |

## 元数据说明

### PDF文件

| 元数据 | 说明 | 示例 |
|--------|------|------|
| `source` | 文件名 | `南京工业职业技术学院工作制度汇编.pdf` |
| `page` | 页码 | `15` |
| `section` | 章节标题 | `学生请假管理规定` |
| `has_table` | 是否包含表格 | `true` / `false` |

### Word文件

| 元数据 | 说明 | 示例 |
|--------|------|------|
| `source` | 文件名 | `成果转化备案登记表.docx` |
| `section` | 所属章节 | `成果转化流程` |
| `is_table` | 是否为表格内容 | `true` / `false` |

### Excel文件

| 元数据 | 说明 | 示例 |
|--------|------|------|
| `source` | 文件名 | `学科代码表.xlsx` |
| `sheet` | 工作表名 | `国家社科基金学科分类代码表` |
| `row` | 行号 | `3` |
| `is_header` | 是否为表头 | `true` / `false` |

## 检索结果定位

检索结果会显示详细的位置信息，方便定位原文：

```
参考片段:
  [1] 南京工业职业技术学院工作制度汇编.pdf 第15页 【学生请假管理规定】: ...
  [2] 学科代码表.xlsx [国家社科基金学科分类代码表 第3行]: ...
  [3] 成果转化备案登记表.docx 【表格】: ...
```

## 配置说明

在 `rag_demo.py` 中修改以下配置：

```python
# 向量模型路径
EMBEDDING_MODEL_PATH = "./bge-base-zh-v1.5"

# 向量数据库路径
CHROMA_DB_PATH = "./chroma_db"

# 文档目录
DOCUMENTS_PATH = "./documents"

# Qwen API 配置
API_KEY = "your-api-key"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.5-plus"
```

## 支持的文件格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| PDF | `.pdf` | 提取文本，保留页码和表格检测 |
| Word | `.docx` | 提取段落和表格，识别章节结构 |
| Excel | `.xlsx` | 按行提取，保留工作表和行号 |
| 文本 | `.txt` | 自动检测编码（UTF-8/GBK） |

**注意：** 旧版 `.doc` 格式支持有限，建议转换为 `.docx` 格式。

## 常见问题

### Q: 如何更换大模型？

修改 `rag_demo.py` 中的 API 配置：

```python
API_KEY = "your-api-key"
BASE_URL = "https://api.openai.com/v1"  # OpenAI
MODEL = "gpt-4"
```

### Q: 向量模型加载很慢？

首次加载需要初始化模型，后续会缓存。如需加速，可使用更小的模型：

```python
# 使用更小的模型
EMBEDDING_MODEL_PATH = "BAAI/bge-small-zh-v1.5"  # 需要下载
```

### Q: 如何清空知识库？

```bash
# 交互模式
> /rebuild

# 或删除向量数据库文件夹
rm -rf chroma_db/
```

### Q: PDF解析出错怎么办？

1. 确保PDF不是扫描件（图片型PDF无法提取文本）
2. 检查PDF是否加密
3. 尝试用其他工具转换后再导入

## 技术架构

### RAG问答流程

```
┌─────────────────────────────────────────────────────────────┐
│                      用户输入                                │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    rag_demo.py                               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐ │
│  │ 文档解析     │───→│ BGE Embedding │───→   Chroma      │ │
│  │ PDF/Word/   │    │  (本地模型)   │    │   向量数据库    │ │
│  │ Excel/TXT   │    └─────────────┘    └─────────────────┘ │
│  └─────────────┘              │                   │         │
│                               ▼                   ▼         │
│                        检索相关内容 ◄─────────── 向量检索    │
│                               │                              │
│                               ▼                              │
│                     ┌─────────────────────┐                  │
│                     │  Qwen3.5-plus API   │                  │
│                     └─────────────────────┘                  │
│                               │                              │
│                               ▼                              │
│                          生成回答                             │
└─────────────────────────────────────────────────────────────┘
```

### 智能出题系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    exam_manager.py                           │
│  ┌─────────────────┐              ┌─────────────────────┐   │
│  │  generate_exam  │              │    grade_exam       │   │
│  │   生成试卷       │              │     批阅试卷         │   │
│  └────────┬────────┘              └──────────┬──────────┘   │
│           │                                  │              │
│           ▼                                  ▼              │
│  ┌─────────────────┐              ┌─────────────────────┐   │
│  │ Dify出题API     │              │   Dify批阅API       │   │
│  │ (智能生成题目)   │              │   (自动评分)         │   │
│  └────────┬────────┘              └──────────┬──────────┘   │
│           │                                  │              │
│           ▼                                  ▼              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                    rag_api.py                        │    │
│  │         本地RAG服务（混合检索+Rerank）                │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## 依赖库

| 库名 | 版本 | 用途 |
|------|------|------|
| chromadb | >=1.0 | 向量数据库 |
| sentence-transformers | >=2.0 | 向量模型 |
| openai | >=1.0 | 大模型API |
| pdfplumber | >=0.10 | PDF解析 |
| python-docx | >=1.0 | Word解析 |
| openpyxl | >=3.0 | Excel解析 |
| flask | >=2.0 | API服务 |
| flask-cors | >=3.0 | 跨域支持 |
| rank_bm25 | >=0.2 | BM25检索 |
| jieba | >=0.4 | 中文分词 |

## 版本历史

| 版本 | 更新内容 |
|------|----------|
| v2.1.0 | 添加Dify智能出题系统集成，支持自动出题和批阅 |
| v1.1.0 | RAG幻觉问题优化（混合检索+Rerank+置信度） |
| v1.0.0 | 初始版本：RAG本地知识库问答系统 |

## License

MIT