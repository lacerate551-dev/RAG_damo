"""
Graph RAG 模块

知识图谱增强检索功能，需要 Neo4j 数据库支持。

包含组件：
- graph_manager: Neo4j 图谱管理
- entity_extractor: 实体提取
- graph_rag: 图谱增强检索
- graph_build: 图谱构建工具

使用方式：
    from graph import GraphManager, GraphRAG, EntityExtractor

注意：此模块为可选功能，需在 config.py 中配置：
    USE_GRAPH_RAG = True
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "your_password"
"""

# 延迟导入，避免 Neo4j 未安装时报错
__all__ = [
    'GraphManager',
    'Entity',
    'Triple',
    'get_graph_manager',
    'EntityExtractor',
    'GraphRAG',
    'should_use_graph',
]


def __getattr__(name):
    """延迟导入"""
    if name == 'GraphManager':
        from .graph_manager import GraphManager
        return GraphManager
    elif name == 'Entity':
        from .graph_manager import Entity
        return Entity
    elif name == 'Triple':
        from .graph_manager import Triple
        return Triple
    elif name == 'get_graph_manager':
        from .graph_manager import get_graph_manager
        return get_graph_manager
    elif name == 'EntityExtractor':
        from .entity_extractor import EntityExtractor
        return EntityExtractor
    elif name == 'GraphRAG':
        from .graph_rag import GraphRAG
        return GraphRAG
    elif name == 'should_use_graph':
        from .graph_rag import should_use_graph
        return should_use_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
