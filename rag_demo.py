"""
rag_demo.py - 向后兼容适配层与控制台启动入口

本项目已重构为模块化架构。此文件主要作为旧代码的兼容层，
以及提供便捷的控制台聊天启动方式。

新功能开发请使用:
- core/engine.py: RAG 核心引擎单例
- core/agentic.py: 交互代理与意图控制
- api/application.py: Flask 服务器工厂
- knowledge/manager.py: 多知识库管理器
"""

import sys

# 为可能引用旧变量的文件提供代理
from core.engine import get_engine
try:
    from config import API_KEY, BASE_URL, MODEL
except ImportError:
    pass

def _get_engine():
    return get_engine()

# --- 动态代理属性 ---
class CompatWrapper:
    def __getattr__(self, name):
        engine = _get_engine()
        # 兼容旧的文件级单例
        if name == 'collection':
            return engine.collection
        elif name == 'embedding_model':
            return engine.embedding_model
        elif name == 'reranker':
            return engine.reranker
        elif name == 'llm_client':
            return engine.llm_client
        elif name == 'bm25_index':
            return engine.bm25_index
        elif name == 'search_knowledge':
            return engine.search_knowledge
        elif name == 'generate_answer':
            return engine.generate_answer
        elif name == 'check_restricted_documents':
            return engine.check_restricted_documents
        else:
            raise AttributeError(f"模块 {__name__} 没有属性 {name}")

# 将当前模块替换为代理对象
import sys
sys.modules[__name__] = CompatWrapper()

# 命令行入口
if __name__ == '__main__':
    from core.agentic import main
    main()
