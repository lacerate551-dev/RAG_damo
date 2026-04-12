"""
⚠️ 此文件已迁移至 core/chunker.py
保留此文件仅为兼容旧 import 路径，请迁移到:
    from core.chunker import SemanticChunker, HybridChunker
"""
import warnings as _warnings
_warnings.warn(
    "semantic_chunker 模块已迁移至 core.chunker，请更新 import 路径",
    DeprecationWarning, stacklevel=2
)
from core.chunker import *  # noqa: F401,F403
