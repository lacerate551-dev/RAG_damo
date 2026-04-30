# -*- coding: utf-8 -*-
"""
企业文件系统集成助手

提供便捷方法从企业文件系统获取文件并进行向量化
"""

import os
import tempfile
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def get_file_for_parsing(
    file_path: str,
    use_file_provider: bool = True
) -> Tuple[str, bool]:
    """
    获取用于解析的文件路径

    根据配置自动从本地或企业文件系统获取文件。
    如果是企业文件系统，会下载到临时目录并返回临时路径。

    Args:
        file_path: 文件路径（相对路径或绝对路径）
        use_file_provider: 是否使用文件提供者（默认 True）

    Returns:
        (文件绝对路径, 是否是临时文件需要清理)
    """
    # 如果是绝对路径且文件存在，直接返回
    if os.path.isabs(file_path) and os.path.exists(file_path):
        return file_path, False

    # 如果配置了文件提供者，从企业文件系统获取
    if use_file_provider:
        try:
            from storage import get_file_provider

            provider = get_file_provider()

            # 检查文件是否存在
            if not provider.exists(file_path):
                # 尝试本地 documents 目录
                from config import DOCUMENTS_PATH
                local_path = os.path.join(DOCUMENTS_PATH, file_path)
                if os.path.exists(local_path):
                    return os.path.abspath(local_path), False
                raise FileNotFoundError(f"文件不存在: {file_path}")

            # 获取文件信息
            info = provider.get_file_info(file_path)
            logger.info(f"从企业文件系统获取文件: {file_path} ({info.size} bytes)")

            # 对于大文件，使用流式下载
            if info.size > 100 * 1024 * 1024:  # > 100MB
                logger.info(f"大文件，使用流式下载: {file_path}")
                stream = provider.get_file_stream(file_path)
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=os.path.splitext(file_path)[1]
                )
                try:
                    while True:
                        chunk = stream.read(8192)
                        if not chunk:
                            break
                        temp_file.write(chunk)
                finally:
                    stream.close()
                temp_file.close()
                return temp_file.name, True
            else:
                # 小文件直接下载
                content = provider.get_file(file_path)
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=os.path.splitext(file_path)[1]
                )
                temp_file.write(content)
                temp_file.close()
                return temp_file.name, True

        except ImportError:
            logger.warning("文件提供者模块未安装，使用本地文件系统")

    # 降级到本地文件系统
    from config import DOCUMENTS_PATH
    local_path = os.path.join(DOCUMENTS_PATH, file_path)

    if os.path.exists(local_path):
        return os.path.abspath(local_path), False

    raise FileNotFoundError(f"文件不存在: {file_path}")


def cleanup_temp_file(file_path: str, is_temp: bool):
    """
    清理临时文件

    Args:
        file_path: 文件路径
        is_temp: 是否是临时文件
    """
    if is_temp and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.debug(f"清理临时文件: {file_path}")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")


class FileFetcher:
    """
    文件获取上下文管理器

    使用方式:
        with FileFetcher("finance/报销制度.pdf") as f:
            # f.path 是可用于解析的文件路径
            # 自动处理临时文件清理
            parse_document(f.path, ...)
    """

    def __init__(self, file_path: str, use_file_provider: bool = True):
        self.file_path = file_path
        self.use_file_provider = use_file_provider
        self.temp_path: Optional[str] = None
        self.is_temp = False

    def __enter__(self):
        self.temp_path, self.is_temp = get_file_for_parsing(
            self.file_path,
            self.use_file_provider
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_temp and self.temp_path:
            cleanup_temp_file(self.temp_path, True)
        return False

    @property
    def path(self) -> str:
        """获取文件路径"""
        return self.temp_path


# ==================== 便捷函数 ====================

def fetch_file(file_path: str) -> FileFetcher:
    """
    获取文件（上下文管理器）

    Args:
        file_path: 文件路径

    Returns:
        FileFetcher 上下文管理器

    Example:
        with fetch_file("finance/报销制度.pdf") as f:
            result = parse_document(f.path)
    """
    return FileFetcher(file_path)
