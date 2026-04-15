"""
知识库管理模块

包含：
- manager: 多向量库管理器 (KnowledgeBaseManager)
- router: 知识库路由器 (KnowledgeBaseRouter)
- sync: 知识库同步服务 (KnowledgeSyncService)
- lifecycle: 文档生命周期管理
- diff: 文档差异分析
"""

from .manager import KnowledgeBaseManager
from .router import KnowledgeBaseRouter

try:
    from .sync import KnowledgeSyncService
except ImportError:
    pass

__all__ = [
    'KnowledgeBaseManager', 'KnowledgeBaseRouter', 'KnowledgeSyncService'
]
