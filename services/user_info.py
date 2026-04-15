"""
用户信息服务 - 封装调用前后端用户信息接口

功能：
1. 根据用户 ID 获取用户详情
2. 缓存用户信息减少接口调用
3. 批量获取用户信息

使用方式：
    from services.user_info import UserInfoService

    user_info = UserInfoService(api_base_url="http://backend-api")
    user = user_info.get_user_info("user_123")
    print(user["name"])  # 用户姓名

注意：
- 该服务依赖前后端组提供的用户信息接口
- RAG 系统只存储 user_id，不存储用户姓名等敏感信息
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict, field

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 配置 ====================

# 默认 API 地址（可从环境变量覆盖）
DEFAULT_API_BASE_URL = os.environ.get("USER_API_BASE_URL", "http://localhost:8080/api")

# 缓存过期时间（秒）
CACHE_EXPIRE_SECONDS = int(os.environ.get("USER_INFO_CACHE_EXPIRE", 3600))  # 默认 1 小时


# ==================== 数据类 ====================

@dataclass
class UserInfo:
    """用户信息"""
    user_id: str = ""
    username: str = ""
    name: str = ""           # 真实姓名
    role: str = ""           # 角色：admin/manager/user
    department: str = ""     # 部门
    email: str = ""
    phone: str = ""
    avatar: str = ""
    status: str = "active"   # 状态：active/disabled

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'UserInfo':
        return cls(
            user_id=data.get("user_id", data.get("id", "")),
            username=data.get("username", ""),
            name=data.get("name", data.get("real_name", "")),
            role=data.get("role", "user"),
            department=data.get("department", data.get("dept", "")),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            avatar=data.get("avatar", ""),
            status=data.get("status", "active")
        )


# ==================== 用户信息服务 ====================

class UserInfoService:
    """
    用户信息服务

    封装调用前后端用户信息接口，提供缓存机制减少接口调用次数。
    """

    def __init__(self, api_base_url: str = None, enable_cache: bool = True):
        """
        初始化用户信息服务

        Args:
            api_base_url: 用户 API 基础地址
            enable_cache: 是否启用内存缓存
        """
        self.api_base_url = (api_base_url or DEFAULT_API_BASE_URL).rstrip("/")
        self.enable_cache = enable_cache

        # 内存缓存
        self._cache: Dict[str, Dict] = {}

        # HTTP 客户端（延迟初始化）
        self._client = None

        logger.info(f"用户信息服务初始化: api_base_url={self.api_base_url}, cache={enable_cache}")

    def _get_client(self):
        """获取 HTTP 客户端（延迟初始化）"""
        if self._client is None:
            try:
                import requests
                self._client = requests
            except ImportError:
                logger.warning("requests 库未安装，用户信息服务功能受限")
                self._client = False

        return self._client if self._client else None

    def get_user_info(self, user_id: str, use_cache: bool = True) -> Optional[UserInfo]:
        """
        获取用户信息

        Args:
            user_id: 用户 ID
            use_cache: 是否使用缓存

        Returns:
            UserInfo 对象，获取失败返回 None
        """
        if not user_id:
            return None

        # 检查缓存
        if use_cache and self.enable_cache:
            cached = self._get_from_cache(user_id)
            if cached:
                return cached

        # 调用接口
        user_info = self._fetch_user_info(user_id)

        # 存入缓存
        if user_info and self.enable_cache:
            self._save_to_cache(user_id, user_info)

        return user_info

    def get_user_name(self, user_id: str) -> str:
        """
        获取用户姓名（便捷方法）

        Args:
            user_id: 用户 ID

        Returns:
            用户姓名，获取失败返回 user_id
        """
        user_info = self.get_user_info(user_id)
        if user_info and user_info.name:
            return user_info.name
        return user_id

    def get_users_batch(self, user_ids: List[str]) -> Dict[str, UserInfo]:
        """
        批量获取用户信息

        Args:
            user_ids: 用户 ID 列表

        Returns:
            {user_id: UserInfo} 字典
        """
        results = {}

        # 分离已缓存和未缓存的
        uncached_ids = []
        for user_id in user_ids:
            if self.enable_cache:
                cached = self._get_from_cache(user_id)
                if cached:
                    results[user_id] = cached
                    continue
            uncached_ids.append(user_id)

        # 批量获取未缓存的
        if uncached_ids:
            batch_results = self._fetch_users_batch(uncached_ids)
            for user_id, user_info in batch_results.items():
                results[user_id] = user_info
                if self.enable_cache and user_info:
                    self._save_to_cache(user_id, user_info)

        return results

    def clear_cache(self, user_id: str = None):
        """
        清除缓存

        Args:
            user_id: 用户 ID，不传则清除全部
        """
        if user_id:
            self._cache.pop(user_id, None)
        else:
            self._cache.clear()

    # ==================== 内部方法 ====================

    def _fetch_user_info(self, user_id: str) -> Optional[UserInfo]:
        """调用接口获取用户信息"""
        client = self._get_client()
        if not client:
            logger.warning(f"HTTP 客户端不可用，无法获取用户信息: {user_id}")
            return None

        try:
            url = f"{self.api_base_url}/users/{user_id}"
            response = client.get(url, timeout=5)

            if response.status_code == 200:
                data = response.json()
                # 兼容不同的响应格式
                if "data" in data:
                    data = data["data"]
                return UserInfo.from_dict(data)
            elif response.status_code == 404:
                logger.warning(f"用户不存在: {user_id}")
                return None
            else:
                logger.error(f"获取用户信息失败: {user_id}, status={response.status_code}")
                return None

        except Exception as e:
            logger.error(f"获取用户信息异常: {user_id}, error={e}")
            return None

    def _fetch_users_batch(self, user_ids: List[str]) -> Dict[str, UserInfo]:
        """批量获取用户信息"""
        client = self._get_client()
        if not client:
            return {}

        try:
            url = f"{self.api_base_url}/users/batch"
            response = client.post(
                url,
                json={"user_ids": user_ids},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                results = {}

                # 兼容不同的响应格式
                users = data.get("data", data.get("users", []))
                if isinstance(users, list):
                    for user_data in users:
                        user_info = UserInfo.from_dict(user_data)
                        results[user_info.user_id] = user_info
                elif isinstance(users, dict):
                    for user_id, user_data in users.items():
                        results[user_id] = UserInfo.from_dict(user_data)

                return results
            else:
                logger.error(f"批量获取用户信息失败: status={response.status_code}")
                return {}

        except Exception as e:
            logger.error(f"批量获取用户信息异常: {e}")
            return {}

    def _get_from_cache(self, user_id: str) -> Optional[UserInfo]:
        """从缓存获取用户信息"""
        if user_id not in self._cache:
            return None

        cached = self._cache[user_id]
        expire_at = cached.get("expire_at")

        if expire_at and datetime.now() > expire_at:
            # 缓存已过期
            self._cache.pop(user_id, None)
            return None

        return cached.get("data")

    def _save_to_cache(self, user_id: str, user_info: UserInfo):
        """保存用户信息到缓存"""
        self._cache[user_id] = {
            "data": user_info,
            "expire_at": datetime.now() + timedelta(seconds=CACHE_EXPIRE_SECONDS)
        }


# ==================== 全局实例 ====================

_user_info_service: Optional[UserInfoService] = None


def get_user_info_service() -> UserInfoService:
    """获取全局用户信息服务实例"""
    global _user_info_service
    if _user_info_service is None:
        _user_info_service = UserInfoService()
    return _user_info_service


def get_user_info(user_id: str) -> Optional[UserInfo]:
    """便捷函数：获取用户信息"""
    return get_user_info_service().get_user_info(user_id)


def get_user_name(user_id: str) -> str:
    """便捷函数：获取用户姓名"""
    return get_user_info_service().get_user_name(user_id)


# ==================== 测试代码 ====================

if __name__ == "__main__":
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("用户信息服务测试")
    print("=" * 60)

    # 创建服务（使用模拟数据）
    service = UserInfoService(api_base_url="http://mock-api", enable_cache=True)

    # 测试模拟数据（由于没有真实接口，这里只测试数据结构）
    print("\n[1] 测试 UserInfo 数据结构...")
    mock_user = UserInfo(
        user_id="user_001",
        username="zhangsan",
        name="张三",
        role="manager",
        department="财务部",
        email="zhangsan@example.com"
    )
    print(f"  用户ID: {mock_user.user_id}")
    print(f"  姓名: {mock_user.name}")
    print(f"  角色: {mock_user.role}")
    print(f"  部门: {mock_user.department}")

    # 测试字典转换
    print("\n[2] 测试字典转换...")
    user_dict = mock_user.to_dict()
    print(f"  to_dict: {user_dict}")

    restored = UserInfo.from_dict(user_dict)
    print(f"  from_dict: {restored.name}")

    # 测试缓存机制
    print("\n[3] 测试缓存机制...")
    service._save_to_cache("test_user", mock_user)
    cached = service._get_from_cache("test_user")
    print(f"  缓存命中: {cached.name if cached else 'None'}")

    service.clear_cache("test_user")
    cached_after_clear = service._get_from_cache("test_user")
    print(f"  清除后: {cached_after_clear}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
