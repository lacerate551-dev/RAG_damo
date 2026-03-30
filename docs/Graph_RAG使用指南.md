# Graph RAG 使用指南

Graph RAG 是在传统向量检索基础上，结合知识图谱进行增强检索的方案。本文档介绍如何使用和配置 Graph RAG 功能。

## 功能概述

### 核心能力

| 功能 | 说明 |
|------|------|
| 实体提取 | LLM 自动从文档中提取实体和关系 |
| 图谱构建 | 将三元组存入 Neo4j 图数据库 |
| 图谱检索 | 基于实体进行多跳推理查询 |
| 融合检索 | 向量检索 + 图谱检索结果融合 |

### 适用场景

Graph RAG 特别适合以下查询类型：

- **关系查询**：「XX部门负责哪些制度？」
- **多跳推理**：「发生安全事件后应该向谁报告？」
- **条件判断**：「什么情况下可以申请XX？」
- **流程追溯**：「报销流程包含哪些步骤？」

## 环境准备

### 1. 安装 Neo4j

**Docker 方式（推荐）**

```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -v neo4j_data:/data \
  neo4j:latest
```

**验证安装**

- 访问 http://localhost:7474
- 用户名：neo4j
- 密码：password123

### 2. 安装 Python 依赖

```bash
pip install neo4j
```

### 3. 配置 config.py

```python
# Neo4j 配置
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"
USE_GRAPH_RAG = True  # 启用图谱检索
```

## 快速开始

### 1. 准备文档

将文档放入 `documents/` 目录，支持：
- PDF (.pdf)
- Word (.docx)
- Excel (.xlsx)
- TXT (.txt)

### 2. 构建向量索引

```bash
python rag_demo.py --rebuild
```

### 3. 构建知识图谱

```bash
python graph_build.py
```

输出示例：
```
============================================================
Graph RAG 图谱构建
============================================================
[1/3] 连接 Neo4j...
✓ 已连接到 Neo4j: bolt://localhost:7687

[2/3] 加载文档...
      找到 1 个文档

[3/3] 提取实体和关系...
      处理: 信息安全管理制度.txt
      提取到 68 个实体, 82 个关系

============================================================
构建完成！
节点数: 68
关系数: 82
类型分布: {'部门': 5, '制度': 8, '人员': 12, ...}
============================================================
```

### 4. 测试图谱检索

```bash
python graph_test.py
```

或在 Python 中：

```python
from graph_rag import GraphRAG

rag = GraphRAG()
result = rag.search("信息技术部负责什么？", verbose=True)

print(result.answer)
print(f"实体: {result.entities}")
print(f"图谱上下文: {'有' if result.graph_context else '无'}")
```

## API 使用

### 图谱检索

```bash
curl -X POST http://localhost:5001/graph/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "发生一级安全事件后应该向谁报告？",
    "top_k": 5,
    "depth": 2
  }'
```

响应：
```json
{
  "answer": "根据信息安全管理制度，发生一级安全事件后...",
  "entities": ["一级安全事件", "应急响应小组", "安全部门"],
  "has_graph_context": true,
  "sources": [...],
  "graph_context": "【知识图谱信息】\n实体关系：\n- 一级安全事件 属于 安全事件\n- 安全事件 报告 应急响应小组..."
}
```

### 获取图谱统计

```bash
curl http://localhost:5001/graph/stats
```

响应：
```json
{
  "enabled": true,
  "connected": true,
  "nodes": 68,
  "edges": 82,
  "types": {
    "部门": 5,
    "制度": 8,
    "人员": 12,
    "流程": 6,
    "条件": 15
  }
}
```

## 实体类型

系统自动识别以下实体类型：

| 类型 | 说明 | 示例 |
|------|------|------|
| 部门 | 组织机构 | 人力资源部、财务部、信息技术部 |
| 制度 | 规章制度 | 差旅管理办法、信息安全管理制度 |
| 人员 | 角色岗位 | 员工、经理、审批人、管理员 |
| 流程 | 业务流程 | 报销流程、审批流程、入职流程 |
| 条件 | 适用条件 | 享受条件、申请条件、适用范围 |
| 金额 | 限额标准 | 补助标准、报销限额 |
| 时间 | 时效规定 | 申请时限、有效期 |

## 关系类型

| 关系 | 英文映射 | 说明 |
|------|----------|------|
| 负责 | RESPONSIBLE_FOR | 部门负责制度 |
| 适用 | APPLIES_TO | 制度适用对象 |
| 包含 | CONTAINS | 流程包含步骤 |
| 审批 | APPROVES | 人员审批事项 |
| 限额 | HAS_LIMIT | 制度金额限制 |
| 时效 | HAS_DEADLINE | 时效规定 |
| 条件 | HAS_CONDITION | 适用条件 |
| 相关 | RELATED_TO | 相关联 |
| 属于 | BELONGS_TO | 归属关系 |
| 管理 | MANAGES | 管理关系 |

## 多跳查询示例

### 示例 1：职责追溯

```
查询：发生一级安全事件后应该向谁报告？

图谱推理：
  一级安全事件 --属于--> 安全事件
  安全事件 --报告--> 应急响应小组
  应急响应小组 --由--> 安全部门负责

答案：应向应急响应小组报告，由安全部门负责处理
```

### 示例 2：制度关系

```
查询：差旅管理办法由哪个部门负责？

图谱推理：
  差旅管理办法 --负责部门--> 人力资源部

答案：由人力资源部负责
```

### 示例 3：流程追溯

```
查询：导出机密数据需要哪些审批？

图谱推理：
  机密数据 --导出--> 审批流程
  审批流程 --包含--> 部门负责人审批
  审批流程 --包含--> 安全部门审批

答案：需要部门负责人和安全部门审批
```

## 配置选项

### graph_build.py 参数

```python
# 文档处理
CHUNK_SIZE = 1000      # 文档分块大小
CHUNK_OVERLAP = 200    # 分块重叠

# 实体提取
MAX_ENTITIES = 50      # 每块最大实体数
MAX_RELATIONS = 100    # 每块最大关系数

# 图谱构建
BATCH_SIZE = 100       # 批量插入大小
```

### graph_rag.py 参数

```python
# 检索参数
top_k = 5              # 向量检索数量
graph_depth = 2        # 图谱搜索深度

# 实体提取
max_entities = 5       # 从查询提取的最大实体数
```

## 性能优化

### 1. 图谱索引

Neo4j 自动创建索引，但可以为常用查询添加：

```cypher
// 创建实体名称索引
CREATE INDEX entity_name IF NOT EXISTS FOR (n) ON (n.name)

// 创建实体类型索引
CREATE INDEX entity_type IF NOT EXISTS FOR (n) ON (n.type)
```

### 2. 查询优化

- 限制搜索深度（depth=2 通常足够）
- 限制返回节点数量
- 使用实体类型过滤

### 3. 缓存策略

- 实体提取结果可缓存
- 常用查询结果可缓存

## 故障排除

### Q: Neo4j 连接失败

1. 确认 Docker 容器运行：`docker ps | grep neo4j`
2. 检查端口：`docker port neo4j`
3. 验证密码：访问 http://localhost:7474

### Q: 图谱构建失败

1. 检查文档格式是否正确
2. 确认 LLM API 可用
3. 查看错误日志

### Q: 图谱检索无结果

1. 确认图谱已构建：`curl http://localhost:5001/graph/stats`
2. 检查实体名称是否正确
3. 尝试增加搜索深度

### Q: 实体提取不准确

1. 调整 `entity_extractor.py` 中的 Prompt
2. 增加示例数据
3. 使用更强大的 LLM

## 最佳实践

1. **文档质量**：确保文档结构清晰，关系明确
2. **增量构建**：新文档可以增量添加到图谱
3. **定期重建**：定期重建图谱以保持一致性
4. **查询优化**：使用具体实体名称进行查询
5. **结果验证**：对重要查询结果进行人工验证

## 参考资料

- [Neo4j 官方文档](https://neo4j.com/docs/)
- [知识图谱构建最佳实践](https://neo4j.com/developer-guide/knowledge-graph/)
- [Graph RAG 论文](https://arxiv.org/abs/2404.16130)
