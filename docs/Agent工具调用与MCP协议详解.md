# Agent 工具调用与 MCP 协议详解

## 研究目标

理解智能体（Agent）中：
1. 大模型如何准确调用工具（Function Calling 机制）
2. MCP 协议是什么，与传统工具调用的区别

---

## 一、大模型工具调用的核心原理

### 1.1 本质：结构化输出生成

工具调用本质是**让模型生成结构化的 JSON 输出**，而非自然语言：

```
用户输入 + 工具定义 → 模型推理 → 选择工具 + 生成参数(JSON)
```

模型经过特殊训练，能够：
1. **理解工具定义**：解析工具名称、描述、参数 schema
2. **判断调用时机**：根据用户输入决定是否需要调用工具
3. **生成结构化参数**：按 JSON Schema 格式输出参数

### 1.2 Claude 工具调用示例

```python
import anthropic

client = anthropic.Anthropic()

# 1. 定义工具
tools = [
    {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，如：北京、上海"
                }
            },
            "required": ["city"]
        }
    }
]

# 2. 发送请求
message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "北京今天天气怎么样？"}]
)

# 3. 检查模型是否要调用工具
if message.stop_reason == "tool_use":
    for block in message.content:
        if block.type == "tool_use":
            tool_name = block.name      # "get_weather"
            tool_input = block.input    # {"city": "北京"}
            tool_id = block.id          # 用于返回结果

# 4. 执行工具后，返回结果给模型继续对话
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=tools,
    messages=[
        {"role": "user", "content": "北京今天天气怎么样？"},
        {"role": "assistant", "content": [tool_use_block]},
        {"role": "user", "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "北京今天晴天，气温 18°C"
            }
        ]}
    ]
)
```

### 1.3 OpenAI Function Calling 示例

```python
from openai import OpenAI

client = OpenAI()

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "北京天气怎么样？"}],
    tools=[
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取城市天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"}
                    },
                    "required": ["city"]
                }
            }
        }
    ],
    tool_choice="auto"  # auto | required | none
)

# 检查是否需要调用工具
if response.choices[0].message.tool_calls:
    tool_call = response.choices[0].message.tool_calls[0]
    function_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)
```

### 1.4 模型如何"准确"选择工具

```
┌─────────────────────────────────────────────────────────┐
│                    工具选择流程                          │
├─────────────────────────────────────────────────────────┤
│  1. 解析用户意图 - 理解用户想要做什么                     │
│  2. 匹配工具描述 - 根据工具名和描述进行语义匹配            │
│  3. 验证参数可行性 - 检查是否有足够信息构造参数           │
│  4. 生成结构化输出 - 按 input_schema 生成 JSON           │
└─────────────────────────────────────────────────────────┘
```

**关键因素：**
| 因素 | 影响 |
|------|------|
| 工具描述质量 | 清晰的 description 能大幅提高匹配准确率 |
| 参数描述精确性 | 每个参数需要详细说明用途和约束 |
| 工具数量 | 工具越多，选择难度越大（建议不超过 10-20 个）|
| 用户意图清晰度 | 模糊请求可能导致错误选择 |

---

## 二、JSON Schema 工具定义详解

JSON Schema 是定义工具参数的标准格式：

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "搜索关键词"
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 10
    },
    "filters": {
      "type": "object",
      "properties": {
        "category": {"type": "array", "items": {"type": "string"}}
      }
    }
  },
  "required": ["query"]
}
```

**常用类型：**

| 类型 | 说明 | 示例 |
|------|------|------|
| `string` | 字符串 | `{"type": "string"}` |
| `integer` | 整数 | `{"type": "integer", "minimum": 0}` |
| `number` | 浮点数 | `{"type": "number"}` |
| `boolean` | 布尔值 | `{"type": "boolean"}` |
| `array` | 数组 | `{"type": "array", "items": {...}}` |
| `object` | 对象 | `{"type": "object", "properties": {...}}` |
| `enum` | 枚举 | `{"type": "string", "enum": ["a", "b", "c"]}` |

---

## 三、MCP (Model Context Protocol) 协议

### 3.1 什么是 MCP

**MCP 是 Anthropic 2024 年推出的开放协议**，旨在标准化 AI 应用与外部资源的连接。

```
类比：USB-C 接口统一了外设连接
     MCP 统一了 AI 与外部资源的连接
```

**核心能力：**
- 连接各种数据源（数据库、文件系统、API）
- 使用外部工具
- 访问预定义的提示词模板（Prompts）
- 保持与上下文的持久连接

### 3.2 MCP 架构

```
┌──────────────────────────────────────────────────────────┐
│                      MCP 架构                            │
├──────────────────────────────────────────────────────────┤
│                                                          │
│   ┌─────────────┐         ┌─────────────┐               │
│   │  MCP Host   │ ◄─────► │ MCP Client  │ ◄─────► MCP   │
│   │ (Claude App)│         │  (连接器)    │         Server│
│   └─────────────┘         └─────────────┘               │
│         │                                               │
│         ▼                                               │
│   ┌─────────────┐                               ┌──────┐│
│   │  AI Model   │                               │数据源/││
│   │  (Claude)   │                               │工具   ││
│   └─────────────┘                               └──────┘│
└──────────────────────────────────────────────────────────┘
```

| 组件 | 角色 | 示例 |
|------|------|------|
| **MCP Host** | 运行 AI 应用的宿主 | Claude Desktop, IDE 插件 |
| **MCP Client** | 管理与服务器的连接 | 内置在 Host 中 |
| **MCP Server** | 提供工具、资源、提示词 | PostgreSQL Server, GitHub Server |

### 3.3 MCP 核心功能

#### Tools（工具）
```python
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="query_database",
            description="执行 SQL 查询",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL 语句"}
                },
                "required": ["sql"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "query_database":
        result = await db.query(arguments["sql"])
        return [{"type": "text", "text": str(result)}]
```

#### Resources（资源）- 只读数据源
```python
@server.list_resources()
async def list_resources():
    return [
        Resource(uri="file:///project/README.md", name="README")
    ]

@server.read_resource()
async def read_resource(uri: str):
    # 返回资源内容
    return open(uri[7:]).read()
```

#### Prompts（提示词模板）
```python
@server.list_prompts()
async def list_prompts():
    return [
        Prompt(name="code_review", description="代码审查提示词")
    ]
```

### 3.4 MCP 传输方式

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| **Stdio** | 本地工具 | 服务器作为子进程，通过 stdin/stdout 通信 |
| **HTTP + SSE** | 远程服务 | 通过 HTTP 和 Server-Sent Events 通信 |

### 3.5 MCP 配置示例

```json
// Claude Desktop 配置 (claude_desktop_config.json)
{
  "mcpServers": {
    "postgres": {
      "command": "mcp-server-postgres",
      "args": ["postgresql://localhost/mydb"]
    },
    "github": {
      "command": "mcp-server-github",
      "args": ["--token", "${GITHUB_TOKEN}"]
    }
  }
}
```

配置后，MCP 服务器**自动**：
- 向 AI 暴露可用工具
- 提供资源访问
- 无需修改应用代码

---

## 四、Function Calling vs MCP 对比

| 特性 | Function Calling | MCP 协议 |
|------|------------------|----------|
| **标准化** | 各厂商格式不同 | 统一开放标准 |
| **工具发现** | 需硬编码工具定义 | 动态发现 |
| **上下文管理** | 需手动管理 | 内置资源管理 |
| **跨平台** | 限于特定 API | 任何 MCP 兼容应用 |
| **扩展性** | 添加工具需改代码 | 插件式架构 |
| **提示词模板** | 不支持 | 内置支持 |
| **资源访问** | 需自行实现 | 标准化接口 |
| **实现复杂度** | 简单直接 | 需要服务器实现 |

### 选择建议

| 场景 | 推荐方案 |
|------|---------|
| 简单场景、单次 API 调用 | Function Calling |
| 需要资源访问、多应用复用 | MCP |
| 快速原型开发 | Function Calling |
| 生产环境、需要标准化 | MCP |

---

## 五、关键要点总结

1. **工具调用本质**：大模型生成结构化 JSON，而非直接执行代码
2. **准确性的关键**：清晰的工具描述 + 精确的参数 Schema
3. **MCP 的价值**：统一标准，实现"一次开发，处处可用"
4. **MCP 三大能力**：Tools（工具）、Resources（资源）、Prompts（提示词）

---

## 参考资源

- [Anthropic Tool Use 文档](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [OpenAI Function Calling 指南](https://platform.openai.com/docs/guides/function-calling)
- [MCP 官方规范](https://modelcontextprotocol.io/)
- [MCP GitHub 仓库](https://github.com/modelcontextprotocol)
