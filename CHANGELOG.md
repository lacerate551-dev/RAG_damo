# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [1.0.0] - 2025-03-26

### Added
- 初始版本：RAG本地知识库问答系统
- 支持PDF、Word、Excel、TXT格式
- 本地向量模型 bge-base-zh-v1.5
- Chroma向量数据库
- Qwen3.5-plus API调用