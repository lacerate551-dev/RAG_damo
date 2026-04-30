# -*- coding: utf-8 -*-
"""
存储模块

提供统一的文件存储抽象层，支持多种存储后端
"""

from .file_provider import (
    FileProvider,
    FileInfo,
    LocalFileProvider,
    SMBFileProvider,
    S3FileProvider,
    HttpFileProvider,
    get_file_provider,
    reset_provider
)

from .file_fetcher import (
    get_file_for_parsing,
    cleanup_temp_file,
    FileFetcher,
    fetch_file
)

__all__ = [
    # 文件提供者
    'FileProvider',
    'FileInfo',
    'LocalFileProvider',
    'SMBFileProvider',
    'S3FileProvider',
    'HttpFileProvider',
    'get_file_provider',
    'reset_provider',
    # 文件获取
    'get_file_for_parsing',
    'cleanup_temp_file',
    'FileFetcher',
    'fetch_file'
]
