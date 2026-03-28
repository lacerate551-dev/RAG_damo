# Dify Cloud 快速入门指南

## 第一步：注册Dify Cloud

1. 访问 https://cloud.dify.ai
2. 使用GitHub或Google账号登录
3. 首次登录可获得免费额度

## 第二步：创建知识库

1. 进入Dify控制台
2. 点击左侧「知识库」→「创建知识库」
3. 上传文档：
   - 点击「上传文件」
   - 选择 `documents/` 目录下的PDF、Word、Excel文件
   - 等待文档处理完成

4. 配置向量化：
   - 嵌入模型：选择 `text-embedding-3-small` 或其他可用模型
   - 分块设置：
     - 分块大小：1000字符
     - 分块重叠：100字符

## 第三步：创建出题工作流

### 3.1 创建工作流应用

1. 点击「工作室」→「创建应用」
2. 选择「Workflow」类型
3. 命名为「智能出题」

### 3.2 配置工作流节点

```
┌─────────────┐
│   开始节点   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│        输入变量节点                   │
│  topic: 主题 (文本输入)              │
│  choice_count: 选择题数量 (数字 0-10) │
│  blank_count: 填空题数量 (数字 0-10)  │
│  short_answer_count: 简答题数量 (数字 0-10) │
│  difficulty: 难度 (数字 1-5)         │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│        知识检索节点                   │
│  知识库: 选择刚创建的知识库          │
│  查询内容: {{topic}}                 │
│  Top K: 10                           │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│        LLM节点                       │
│  模型: Qwen-plus 或 GPT-4            │
│  系统提示词: (见下方)                │
│  用户输入: (见下方)                  │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│        结束节点                       │
│  输出变量: questions (LLM输出)       │
└─────────────────────────────────────┘
```

> **说明**：每道题型数量可设为0，如果不想要该类型题目。一次调用生成完整试卷。

### 3.3 LLM节点配置

**系统提示词：**
```
你是一位专业的教育工作者和命题专家。你的任务是根据给定的知识内容，生成一套完整的试卷，包含选择题、填空题和简答题。

你需要遵循以下原则：
1. 题目必须严格基于给定的知识内容，不能编造或扩展
2. 题目应考查对知识的理解和应用，而非死记硬背
3. 选择题干扰项要有迷惑性但不能有歧义
4. 每道题目都应有清晰的解析
5. 如果某类型题目数量为0，则跳过该类型
```

**用户输入模板：**
```
请根据以下知识内容，生成一套完整的试卷：

【主题】
{{topic}}

【知识内容】
{{knowledge_retrieval_result}}

【题目数量】
- 选择题：{{choice_count}} 道
- 填空题：{{blank_count}} 道
- 简答题：{{short_answer_count}} 道
- 难度：{{difficulty}} 级（1最易，5最难）

【各题型格式要求】

选择题格式：
- 题干清晰明确
- 4个选项（A/B/C/D）
- 只有一个正确答案
- 提供解析说明正确答案的原因

填空题格式：
- 题干中用______表示空缺处
- 每个空缺处填写一个答案
- 提供解析说明

简答题格式：
- 题干明确要求
- 参考答案要点（3-5个要点）
- 每个要点的分值

【难度说明】
- 1级：基础记忆题
- 2级：基础理解题
- 3级：应用题
- 4级：综合题
- 5级：难题

【输出格式】
请以JSON格式输出完整试卷：
```json
{
  "choice_questions": [
    {
      "id": 1,
      "content": "题干内容",
      "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
      "answer": "A",
      "analysis": "解析内容",
      "knowledge_points": ["知识点1", "知识点2"],
      "difficulty": 3
    }
  ],
  "blank_questions": [
    {
      "id": 1,
      "content": "题干内容，______处填写答案",
      "answer": "正确答案",
      "analysis": "解析内容",
      "knowledge_points": ["知识点"],
      "difficulty": 2
    }
  ],
  "short_answer_questions": [
    {
      "id": 1,
      "content": "题干内容",
      "reference_answer": {
        "points": [
          {"point": "要点1", "score": 2},
          {"point": "要点2", "score": 2},
          {"point": "要点3", "score": 2}
        ],
        "total_score": 6
      },
      "analysis": "评分要点说明",
      "knowledge_points": ["知识点"],
      "difficulty": 4
    }
  ],
  "total_count": 选择题数+填空题数+简答题数,
  "total_score": 总分
}
```
```

## 第四步：创建批阅工作流

### 4.1 创建工作流应用

1. 点击「工作室」→「创建应用」
2. 选择「Workflow」类型
3. 命名为「自动批阅」

### 4.2 配置输入变量（开始节点）

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `question_id` | 数字 | 题号 |
| `question_type` | 文本 | 题型: choice/blank/short_answer |
| `question_content` | 文本 | 题干内容 |
| `correct_answer` | 文本 | 正确答案 |
| `student_answer` | 文本 | 学生答案 |
| `max_score` | 数字 | 满分 |

### 4.3 配置工作流节点

```
┌─────────────┐
│   开始节点   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│        条件分支节点                   │
│  IF question_type == "choice"       │
│    → 代码节点（规则匹配）             │
│  ELSE                               │
│    → LLM批改节点                     │
└──────┬──────────────────────────────┘
       │
       ├──────────────────┐
       │                  │
       ▼                  ▼
┌─────────────┐    ┌─────────────────┐
│  代码节点    │    │   LLM批改节点    │
│ (选择题匹配) │    │   (填空/简答题)  │
└──────┬──────┘    └────────┬────────┘
       │                    │
       └────────┬───────────┘
                │
                ▼
┌─────────────────────────────────────┐
│        结束节点                       │
│  输出变量: result (批改结果JSON)      │
└─────────────────────────────────────┘
```

### 4.4 代码节点配置（选择题批改）

选择「代码执行」节点，使用Python：

```python
def main(student_answer: str, correct_answer: str, max_score: int) -> dict:
    """
    选择题批改：直接比对答案
    """
    student = student_answer.strip().upper()
    correct = correct_answer.strip().upper()

    if student == correct:
        return {
            "score": max_score,
            "correct": True,
            "feedback": "回答正确！",
            "score_details": [{"point": "正确答案", "earned": max_score, "max": max_score}]
        }
    else:
        return {
            "score": 0,
            "correct": False,
            "feedback": f"回答错误，正确答案是 {correct_answer}",
            "score_details": [{"point": "正确答案", "earned": 0, "max": max_score}]
        }
```

### 4.5 LLM批改节点配置（填空题/简答题）

**系统提示词：**
```
你是一位经验丰富的阅卷老师。请严格按照评分标准批改学生的答案，做到公平、公正、客观。
```

**用户输入模板：**
```
请批改以下答案：

【题型】{{question_type}}

【题目】(满分{{max_score}}分)
{{question_content}}
    
【参考答案】
{{correct_answer}}

【学生答案】
{{student_answer}}

【批改要求】
{% if question_type == "blank" %}
填空题批改要求：
- 答案完全匹配得满分
- 同义词/近义词应酌情给分
- 指出错误之处
{% endif %}

{% if question_type == "short_answer" %}
简答题批改要求：
- 逐条对照参考答案要点
- 表述不同但意思正确的答案应得分
- 指出亮点和不足
- 给出改进建议
{% endif %}

【输出格式】JSON
```json
{
  "score": 得分(数字),
  "max_score": 满分,
  "score_details": [
    {"point": "得分点描述", "earned": 得分, "max": 满分}
  ],
  "highlights": ["答案亮点"],
  "shortcomings": ["不足之处"],
  "suggestions": ["改进建议"],
  "feedback": "整体评语"
}
```
```

> **注意**：在Dify中填写变量时，使用变量选择器从节点列表中选择，不要手写 `{{变量名}}`。

### 4.6 条件分支配置

在条件分支节点中：

| 条件 | 表达式 | 跳转节点 |
|------|--------|----------|
| 条件1 | `question_type` == `choice` | 代码节点 |
| 默认 | 否则 | LLM节点 |

### 4.7 结束节点配置

| 输出变量名 | 来源 |
|------------|------|
| `result` | 条件分支的输出（代码节点或LLM节点的输出） |

## 第五步：测试工作流

### 测试出题

1. 打开「智能出题」工作流
2. 点击「运行」
3. 输入测试参数：
   - topic: "国家社科基金项目申报"
   - choice_count: 3
   - blank_count: 2
   - short_answer_count: 2
   - difficulty: 3
4. 查看输出结果，应包含完整的混合试卷JSON

### 测试批阅

1. 打开「自动批阅」工作流
2. 点击「运行」
3. 输入测试参数：
   ```json
   {
     "question_id": 1,
     "question_type": "short_answer",
     "question_content": "国家社科基金项目有哪些类别？",
     "correct_answer": "重点项目(A)、一般项目(B)、青年项目(C)、后期资助项目(F)、西部项目(X)",
     "student_answer": "有重点项目和一般项目",
     "max_score": 10
   }
   ```
4. 查看批改结果

## 第六步：获取API密钥

1. 在工作流页面，点击「API」
2. 复制API密钥
3. 保存到配置文件，供前端调用

```python
# config.py
DIFY_API_KEY = "app-xxxxxxxx"
DIFY_API_URL = "https://api.dify.ai/v1"
```

## 第七步：本地RAG API服务配置（可选）

> 如果你想使用本地优化的混合检索+Rerank，而不是Dify内置的知识库检索，按此步骤配置。
>
> **注意**：`/search` 接口已整合到主 API 服务 `rag_api_server.py` 中，无需单独启动。

### 7.1 启动本地RAG API

启动服务（与主服务相同）：

```bash
python rag_api_server.py
```

服务启动后，`/search` 接口地址为：`http://localhost:5001/search`

### 7.2 配置内网穿透（ngrok）

Dify Cloud无法访问本地服务，需要内网穿透：

```bash
# 1. 下载安装ngrok: https://ngrok.com/download

# 2. 配置authtoken（从ngrok官网获取）
ngrok config add-authtoken 你的token

# 3. 启动穿透（端口5001）
ngrok http 5001
```

启动后会显示公网地址：
```
Forwarding    https://xxxx-xx-xx.ngrok-free.app -> http://localhost:5001
```

### 7.5 在Dify中配置HTTP节点

在出题工作流中，用HTTP节点替代知识检索节点：

| 配置项 | 值 |
|--------|-----|
| Method | POST |
| URL | `https://你的ngrok地址/search` |
| Headers | `Content-Type: application/json` |
| Body | `{"query": "{{开始节点/topic}}", "top_k": 10}` |

LLM节点中引用检索结果：
```
【知识内容】
{{HTTP节点名称/body/contexts}}
```

### 7.6 测试本地API

```bash
curl -X POST http://127.0.0.1:5001/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"国家社科基金\", \"top_k\": 5}"
```

返回示例：
```json
{
  "contexts": ["文档内容1", "文档内容2", ...],
  "metadatas": [{"source": "文件名", ...}, ...],
  "scores": [0.95, 0.89, ...]
}
```

## 第八步：整合出题与批阅工作流

两个工作流（出题、批阅）是独立的，需要通过调用层整合。

### 8.1 整合架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     exam_manager.py (调用层)                     │
├─────────────────────────────────────────────────────────────────┤
│  1. 调用「智能出题」API → 生成试卷JSON → 保存到题库/            │
│  2. 学生答题 → 提交答案                                         │
│  3. 读取试卷JSON + 学生答案 → 逐题调用「自动批阅」API           │
│  4. 汇总结果 → 生成批阅报告到批阅报告/                          │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 配置API密钥

1. 在Dify中获取两个工作流的API密钥：
   - 智能出题工作流 → API → 复制API Key
   - 自动批阅工作流 → API → 复制API Key

2. 配置环境变量：
```bash
# Windows
set DIFY_QUESTION_API_KEY=app-xxxxx
set DIFY_GRADE_API_KEY=app-xxxxx

# Linux/Mac
export DIFY_QUESTION_API_KEY=app-xxxxx
export DIFY_GRADE_API_KEY=app-xxxxx
```

或直接修改 `exam_manager.py` 中的配置：
```python
DIFY_QUESTION_API_KEY = "app-xxxxx"  # 出题工作流
DIFY_GRADE_API_KEY = "app-xxxxx"     # 批阅工作流
```

### 8.3 使用示例

**生成试卷：**
```python
from exam_manager import generate_exam, save_exam

# 生成试卷
exam = generate_exam(
    topic="国家社科基金项目申报",
    choice_count=3,
    blank_count=2,
    short_answer_count=2,
    difficulty=3
)

# 保存到题库
save_exam(exam, "test1")
# 保存到: 题库/test1.json
```

**批阅试卷：**
```python
from exam_manager import grade_exam, save_grade_report

# 学生答案
student_answers = {
    "choice_1": "A",
    "choice_2": "B",
    "choice_3": "C",
    "blank_1": "重点课题",
    "blank_2": "申请人",
    "short_answer_1": "国家社科基金项目包括重点项目、一般项目和青年项目等类别",
    "short_answer_2": "申报流程包括提交申请书、专家评审、立项审批等步骤"
}

# 批阅
report = grade_exam("./题库/test1.json", student_answers)

# 保存报告
save_grade_report(report, "张三")
# 保存到: 批阅报告/张三_20240101_120000.json
```

### 8.4 批阅流程说明

| 题型 | 批阅方式 | 正确答案来源 |
|------|----------|--------------|
| 选择题 | 代码规则匹配（精确比对A/B/C/D） | 试卷JSON中的 `answer` 字段 |
| 填空题 | LLM批改（支持同义词判断） | 试卷JSON中的 `answer` 字段 |
| 简答题 | LLM批改（按得分点评分） | 试卷JSON中的 `reference_answer` 字段 |

### 8.5 批阅报告格式

```json
{
  "exam_file": "./题库/test1.json",
  "graded_at": "2024-01-01T12:00:00",
  "total_score": 18,
  "max_score": 30,
  "score_rate": 60.0,
  "questions": [
    {
      "type": "choice",
      "id": 1,
      "content": "题干内容...",
      "student_answer": "A",
      "correct_answer": "B",
      "score": 0,
      "max_score": 2,
      "feedback": "回答错误，正确答案是 B",
      "correct": false
    },
    {
      "type": "short_answer",
      "id": 1,
      "content": "题干内容...",
      "student_answer": "学生作答...",
      "reference_answer": {...},
      "score": 6,
      "max_score": 10,
      "feedback": "整体评语",
      "highlights": ["答案亮点"],
      "shortcomings": ["不足之处"],
      "suggestions": ["改进建议"]
    }
  ]
}
```

### 8.6 目录结构

```
项目目录/
├── 题库/
│   ├── test1.json          # 生成的试卷
│   ├── test2.json
│   └── ...
├── 批阅报告/
│   ├── 张三_20240101.json
│   ├── 李四_20240101.json
│   └── ...
├── exam_manager.py         # 整合管理器
├── rag_api_server.py       # RAG API服务（含/search接口）
└── rag_demo.py             # 原RAG系统
```

## 常见问题

**Q: 知识库检索效果不好？**
A: 尝试调整：
- 增加检索Top K
- 优化分块大小
- 在查询中加入更多关键词

**Q: 生成的题目质量不高？**
A: 尝试：
- 优化系统提示词
- 提高模型等级（如使用GPT-4）
- 增加知识内容的详细程度

**Q: 批改不够准确？**
A: 尝试：
- 提供更详细的评分标准
- 在参考答案中明确得分点
- 使用更强的模型

---

完成以上步骤后，你就可以在Dify Cloud上使用智能出题和自动批阅功能了！
