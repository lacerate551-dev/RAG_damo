# -*- coding: utf-8 -*-
"""
文件存储提供者 - 支持多种存储后端

支持的后端类型:
1. local - 本地文件系统
2. smb/cifs - Windows 共享目录
3. nfs - Linux 网络文件系统
4. s3 - S3 兼容对象存储 (MinIO, OSS, COS 等)
5. http - HTTP API 方式获取文件

使用方式:
    from storage.file_provider import get_file_provider

    provider = get_file_provider()

    # 获取文件内容
    content = provider.get_file("finance/报销制度.pdf")

    # 获取文件流 (用于大文件)
    with provider.get_file_stream("finance/报销制度.pdf") as f:
        # 处理文件流

    # 获取文件元信息
    info = provider.get_file_info("finance/报销制度.pdf")
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, BinaryIO
from dataclasses import dataclass
from pathlib import Path
import threading

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """文件信息"""
    path: str              # 文件路径
    size: int              # 文件大小 (字节)
    content_type: str      # MIME 类型
    last_modified: str     # 最后修改时间 (ISO 格式)
    metadata: Dict[str, Any] = None  # 额外元数据


class FileProvider(ABC):
    """文件存储提供者基类"""

    @abstractmethod
    def get_file(self, path: str) -> bytes:
        """
        获取文件内容

        Args:
            path: 文件相对路径

        Returns:
            文件二进制内容
        """
        pass

    @abstractmethod
    def get_file_stream(self, path: str) -> BinaryIO:
        """
        获取文件流 (用于大文件)

        Args:
            path: 文件相对路径

        Returns:
            文件流对象
        """
        pass

    @abstractmethod
    def get_file_info(self, path: str) -> Optional[FileInfo]:
        """
        获取文件信息

        Args:
            path: 文件相对路径

        Returns:
            文件信息对象，文件不存在返回 None
        """
        pass

    @abstractmethod
    def list_files(self, prefix: str = "", limit: int = 1000) -> list:
        """
        列出文件

        Args:
            prefix: 路径前缀
            limit: 最大返回数量

        Returns:
            文件路径列表
        """
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查文件是否存在"""
        pass


# ==================== 本地文件系统提供者 ====================

class LocalFileProvider(FileProvider):
    """本地文件系统提供者"""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        if not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, path: str) -> Path:
        """解析相对路径为绝对路径"""
        full_path = (self.base_path / path).resolve()
        # 安全检查：防止路径穿越
        if not str(full_path).startswith(str(self.base_path.resolve())):
            raise ValueError(f"非法路径: {path}")
        return full_path

    def get_file(self, path: str) -> bytes:
        full_path = self._resolve_path(path)
        with open(full_path, 'rb') as f:
            return f.read()

    def get_file_stream(self, path: str) -> BinaryIO:
        full_path = self._resolve_path(path)
        return open(full_path, 'rb')

    def get_file_info(self, path: str) -> Optional[FileInfo]:
        full_path = self._resolve_path(path)
        if not full_path.exists():
            return None

        stat = full_path.stat()
        ext = full_path.suffix.lower()

        # 简单的 MIME 类型推断
        mime_types = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
        }

        from datetime import datetime
        return FileInfo(
            path=path,
            size=stat.st_size,
            content_type=mime_types.get(ext, 'application/octet-stream'),
            last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat()
        )

    def list_files(self, prefix: str = "", limit: int = 1000) -> list:
        full_path = self._resolve_path(prefix) if prefix else self.base_path

        files = []
        for p in full_path.rglob('*'):
            if p.is_file():
                rel_path = str(p.relative_to(self.base_path))
                files.append(rel_path)
                if len(files) >= limit:
                    break

        return files

    def exists(self, path: str) -> bool:
        return self._resolve_path(path).exists()


# ==================== SMB/CIFS 提供者 ====================

class SMBFileProvider(FileProvider):
    """
    SMB/CIFS 文件共享提供者

    需要安装: pip install smbprotocol

    配置示例:
        STORAGE_SMB_HOST = "192.168.1.100"
        STORAGE_SMB_SHARE = "共享目录名"
        STORAGE_SMB_USERNAME = "user"
        STORAGE_SMB_PASSWORD = "password"
        STORAGE_SMB_DOMAIN = "DOMAIN"  # 可选
    """

    def __init__(self, host: str, share: str, username: str,
                 password: str, domain: str = "", base_path: str = ""):
        self.host = host
        self.share = share
        self.username = username
        self.password = password
        self.domain = domain
        self.base_path = base_path

        self._session = None
        self._connect()

    def _connect(self):
        """建立 SMB 连接"""
        try:
            from smbprotocol.connection import Connection
            from smbprotocol.session import Session

            # 建立连接
            self._connection = Connection(self.host, 445)
            self._connection.connect()

            # 创建会话
            self._session = Session(
                self._connection,
                self.username,
                self.password,
                require_encryption=False
            )
            self._session.connect()

            logger.info(f"SMB 连接成功: {self.host}/{self.share}")

        except ImportError:
            raise ImportError("请安装 smbprotocol: pip install smbprotocol")
        except Exception as e:
            logger.error(f"SMB 连接失败: {e}")
            raise

    def _get_full_path(self, path: str) -> str:
        return f"{self.base_path}/{path}" if self.base_path else path

    def get_file(self, path: str) -> bytes:
        from smbprotocol.open import Open, ImpersonationLevel, FilePipePrinterAccessMask

        full_path = self._get_full_path(path)

        # 打开文件
        file_open = Open(self._session, self.share, full_path)
        file_open.open(
            desired_access=FilePipePrinterAccessMask.FILE_READ_DATA,
            impersonation_level=ImpersonationLevel.Impersonation
        )

        # 读取内容
        content = file_open.read(0, 0)
        file_open.close()

        return content

    def get_file_stream(self, path: str) -> BinaryIO:
        # SMB 不支持流式访问，先下载到临时文件
        import tempfile
        content = self.get_file(path)

        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_file.write(content)
        temp_file.flush()
        temp_file.seek(0)

        return temp_file

    def get_file_info(self, path: str) -> Optional[FileInfo]:
        from smbprotocol.open import Open, ImpersonationLevel, FilePipePrinterAccessMask

        full_path = self._get_full_path(path)

        try:
            file_open = Open(self._session, self.share, full_path)
            file_open.open(
                desired_access=FilePipePrinterAccessMask.FILE_READ_ATTRIBUTES,
                impersonation_level=ImpersonationLevel.Impersonation
            )

            info = file_open.query_file_info()
            file_open.close()

            from datetime import datetime
            return FileInfo(
                path=path,
                size=info.end_of_file,
                content_type='application/octet-stream',
                last_modified=datetime.fromtimestamp(info.last_write_time.timestamp()).isoformat()
            )
        except Exception:
            return None

    def list_files(self, prefix: str = "", limit: int = 1000) -> list:
        from smbprotocol.open import Open, ImpersonationLevel, FilePipePrinterAccessMask, CreateDisposition

        full_path = self._get_full_path(prefix)

        try:
            dir_open = Open(self._session, self.share, full_path)
            dir_open.open(
                desired_access=FilePipePrinterAccessMask.FILE_LIST_DIRECTORY,
                impersonation_level=ImpersonationLevel.Impersonation,
                create_disposition=CreateDisposition.FILE_OPEN
            )

            results = dir_open.query_directory("*")
            dir_open.close()

            files = [r['file_name'] for r in results if not r['file_name'].startswith('.')]
            return files[:limit]
        except Exception as e:
            logger.error(f"列出文件失败: {e}")
            return []

    def exists(self, path: str) -> bool:
        return self.get_file_info(path) is not None


# ==================== S3 兼容对象存储提供者 ====================

class S3FileProvider(FileProvider):
    """
    S3 兼容对象存储提供者

    支持所有 S3 兼容存储:
    - AWS S3
    - MinIO
    - 阿里云 OSS (S3 兼容模式)
    - 腾讯云 COS (S3 兼容模式)

    需要安装: pip install boto3

    配置示例:
        STORAGE_S3_ENDPOINT = "http://minio.example.com:9000"  # MinIO
        # 或 STORAGE_S3_ENDPOINT = "https://s3.amazonaws.com"  # AWS
        STORAGE_S3_BUCKET = "documents"
        STORAGE_S3_ACCESS_KEY = "minioadmin"
        STORAGE_S3_SECRET_KEY = "minioadmin"
        STORAGE_S3_REGION = "us-east-1"  # 可选
    """

    def __init__(self, endpoint: str, bucket: str, access_key: str,
                 secret_key: str, region: str = "us-east-1"):
        self.endpoint = endpoint
        self.bucket = bucket
        self.region = region

        try:
            import boto3
            from botocore.config import Config

            self._s3 = boto3.client(
                's3',
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=Config(
                    connect_timeout=30,
                    read_timeout=60,
                    retries={'max_attempts': 3}
                )
            )

            # 测试连接
            self._s3.head_bucket(Bucket=bucket)
            logger.info(f"S3 连接成功: {endpoint}/{bucket}")

        except ImportError:
            raise ImportError("请安装 boto3: pip install boto3")
        except Exception as e:
            logger.error(f"S3 连接失败: {e}")
            raise

    def get_file(self, path: str) -> bytes:
        response = self._s3.get_object(Bucket=self.bucket, Key=path)
        return response['Body'].read()

    def get_file_stream(self, path: str) -> BinaryIO:
        response = self._s3.get_object(Bucket=self.bucket, Key=path)
        return response['Body']

    def get_file_info(self, path: str) -> Optional[FileInfo]:
        try:
            response = self._s3.head_object(Bucket=self.bucket, Key=path)

            from datetime import datetime
            return FileInfo(
                path=path,
                size=response['ContentLength'],
                content_type=response.get('ContentType', 'application/octet-stream'),
                last_modified=response['LastModified'].isoformat()
            )
        except Exception:
            return None

    def list_files(self, prefix: str = "", limit: int = 1000) -> list:
        files = []
        continuation_token = None

        while len(files) < limit:
            params = {
                'Bucket': self.bucket,
                'Prefix': prefix,
                'MaxKeys': min(1000, limit - len(files))
            }

            if continuation_token:
                params['ContinuationToken'] = continuation_token

            response = self._s3.list_objects_v2(**params)

            if 'Contents' in response:
                files.extend(obj['Key'] for obj in response['Contents'])

            if not response.get('IsTruncated'):
                break

            continuation_token = response.get('NextContinuationToken')

        return files[:limit]

    def exists(self, path: str) -> bool:
        return self.get_file_info(path) is not None


# ==================== HTTP API 提供者 ====================

class HttpFileProvider(FileProvider):
    """
    HTTP API 文件提供者

    通过 HTTP API 获取文件，适合企业有自建文件管理系统的情况

    配置示例:
        STORAGE_HTTP_BASE_URL = "http://file-server.example.com/api"
        STORAGE_HTTP_TOKEN = "your-api-token"  # 认证 token
    """

    def __init__(self, base_url: str, token: str = "", timeout: int = 60):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout

    def _get_headers(self) -> dict:
        headers = {'Accept': 'application/octet-stream'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    def get_file(self, path: str) -> bytes:
        import requests

        url = f"{self.base_url}/files/{path}"
        response = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
        response.raise_for_status()

        return response.content

    def get_file_stream(self, path: str) -> BinaryIO:
        import requests
        import tempfile

        url = f"{self.base_url}/files/{path}"
        response = requests.get(url, headers=self._get_headers(), stream=True, timeout=self.timeout)
        response.raise_for_status()

        # 写入临时文件返回流
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.flush()
        temp_file.seek(0)

        return temp_file

    def get_file_info(self, path: str) -> Optional[FileInfo]:
        import requests

        url = f"{self.base_url}/files/{path}/info"
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
            if response.status_code == 404:
                return None
            response.raise_for_status()

            data = response.json()
            return FileInfo(
                path=path,
                size=data.get('size', 0),
                content_type=data.get('content_type', 'application/octet-stream'),
                last_modified=data.get('last_modified', ''),
                metadata=data.get('metadata')
            )
        except Exception:
            return None

    def list_files(self, prefix: str = "", limit: int = 1000) -> list:
        import requests

        url = f"{self.base_url}/files"
        params = {'prefix': prefix, 'limit': limit}

        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json().get('files', [])
        except Exception as e:
            logger.error(f"列出文件失败: {e}")
            return []

    def exists(self, path: str) -> bool:
        return self.get_file_info(path) is not None


# ==================== 工厂函数 ====================

_provider_instance: Optional[FileProvider] = None
_provider_lock = threading.Lock()


def get_file_provider() -> FileProvider:
    """
    获取全局文件提供者实例 (单例模式)

    根据 config.py 中的 STORAGE_TYPE 配置创建对应的提供者
    """
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    with _provider_lock:
        if _provider_instance is not None:
            return _provider_instance

        # 从配置读取存储类型
        try:
            from config import STORAGE_TYPE
        except ImportError:
            STORAGE_TYPE = "local"

        if STORAGE_TYPE == "local":
            try:
                from config import DOCUMENTS_PATH
            except ImportError:
                DOCUMENTS_PATH = "documents"

            _provider_instance = LocalFileProvider(DOCUMENTS_PATH)
            logger.info(f"使用本地文件系统: {DOCUMENTS_PATH}")

        elif STORAGE_TYPE in ("smb", "cifs"):
            from config import (
                STORAGE_SMB_HOST, STORAGE_SMB_SHARE,
                STORAGE_SMB_USERNAME, STORAGE_SMB_PASSWORD,
                STORAGE_SMB_DOMAIN, STORAGE_SMB_BASE_PATH
            )
            _provider_instance = SMBFileProvider(
                host=STORAGE_SMB_HOST,
                share=STORAGE_SMB_SHARE,
                username=STORAGE_SMB_USERNAME,
                password=STORAGE_SMB_PASSWORD,
                domain=getattr(STORAGE_SMB_DOMAIN, 'STORAGE_SMB_DOMAIN', ''),
                base_path=getattr(STORAGE_SMB_BASE_PATH, 'STORAGE_SMB_BASE_PATH', '')
            )
            logger.info(f"使用 SMB 存储: {STORAGE_SMB_HOST}/{STORAGE_SMB_SHARE}")

        elif STORAGE_TYPE == "s3":
            from config import (
                STORAGE_S3_ENDPOINT, STORAGE_S3_BUCKET,
                STORAGE_S3_ACCESS_KEY, STORAGE_S3_SECRET_KEY,
                STORAGE_S3_REGION
            )
            _provider_instance = S3FileProvider(
                endpoint=STORAGE_S3_ENDPOINT,
                bucket=STORAGE_S3_BUCKET,
                access_key=STORAGE_S3_ACCESS_KEY,
                secret_key=STORAGE_S3_SECRET_KEY,
                region=getattr(STORAGE_S3_REGION, 'STORAGE_S3_REGION', 'us-east-1')
            )
            logger.info(f"使用 S3 存储: {STORAGE_S3_ENDPOINT}/{STORAGE_S3_BUCKET}")

        elif STORAGE_TYPE == "http":
            from config import (
                STORAGE_HTTP_BASE_URL, STORAGE_HTTP_TOKEN,
                STORAGE_HTTP_TIMEOUT
            )
            _provider_instance = HttpFileProvider(
                base_url=STORAGE_HTTP_BASE_URL,
                token=getattr(STORAGE_HTTP_TOKEN, 'STORAGE_HTTP_TOKEN', ''),
                timeout=getattr(STORAGE_HTTP_TIMEOUT, 'STORAGE_HTTP_TIMEOUT', 60)
            )
            logger.info(f"使用 HTTP 文件服务: {STORAGE_HTTP_BASE_URL}")

        else:
            raise ValueError(f"不支持的存储类型: {STORAGE_TYPE}")

        return _provider_instance


def reset_provider():
    """重置文件提供者实例 (用于测试)"""
    global _provider_instance
    _provider_instance = None


# ==================== 测试 ====================

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("文件存储提供者测试")
    print("=" * 60)

    # 测试本地存储
    print("\n1. 测试本地存储")
    provider = LocalFileProvider("documents")

    # 列出文件
    files = provider.list_files(limit=5)
    print(f"   文件列表 (前5个): {files}")

    # 测试文件信息
    if files:
        info = provider.get_file_info(files[0])
        print(f"   文件信息: {info}")
