"""
网关认证模块 - 从网关注入的 Header 读取用户信息

使用方式：
    from auth_gateway import require_gateway_auth, require_role, get_user_permissions

    @app.route('/protected')
    @require_gateway_auth
    def protected():
        user = request.current_user  # {"user_id": ..., "role": ..., ...}
        ...

    @app.route('/admin')
    @require_gateway_auth
    @require_role('admin')
    def admin_only():
        ...

网关注入的 Header:
    - X-User-ID: 用户唯一标识
    - X-User-Name: 用户名
    - X-User-Role: 用户角色
    - X-User-Department: 部门（可选）

角色权限级别:
    - admin: 可访问所有安全级别的文档 (public, internal, confidential, secret)
    - manager: 可访问 internal 及以下级别的文档 (public, internal, confidential)
    - user: 只能访问公开和内部文档 (public, internal)

向量库权限:
    - admin: 可访问所有向量库，可增删改查、同步
    - manager: 可访问 public + 本部门向量库，可对本部门增删改查、同步
    - user: 可访问 public + 本部门向量库，只读
"""

from functools import wraps
from flask import request, jsonify
from typing import Dict, Optional, List
import os


# ==================== 角色映射配置 ====================
# 后端角色名 -> 本地角色名
# 根据后端实际情况调整此配置
ROLE_MAPPING = {
    # 示例映射（根据后端实际角色名称修改）
    'administrator': 'admin',
    'admin': 'admin',
    'manager': 'manager',
    'user': 'user',
    'normal': 'user',
    'guest': 'user',
    # 添加更多映射...
}

# ==================== 角色权限配置 ====================
# 本地角色 -> 可访问的安全级别（用于文档过滤）
ROLE_PERMISSIONS = {
    'admin': ['public', 'internal', 'confidential'],
    'manager': ['public', 'internal', 'confidential'],
    'user': ['public', 'internal'],
}

# 默认角色（未知角色使用此权限）
DEFAULT_ROLE = 'user'

# ==================== 向量库操作权限配置 ====================
# 定义不同角色对向量库的操作权限
# 操作类型: read, write, delete, sync
COLLECTION_PERMISSIONS = {
    'admin': {
        'read': ['*'],           # 可读取所有向量库
        'write': ['*'],          # 可写入所有向量库
        'delete': ['*'],         # 可删除所有向量库中的文档
        'sync': ['*'],           # 可同步所有向量库
        'create': True,          # 可创建新向量库
        'drop': True,            # 可删除向量库
    },
    'manager': {
        'read': ['public_kb', 'dept_{dept}'],     # 可读取 public 和本部门
        'write': ['dept_{dept}'],                  # 可写入本部门
        'delete': ['dept_{dept}'],                 # 可删除本部门文档
        'sync': ['dept_{dept}'],                   # 可同步本部门
        'create': False,
        'drop': False,
    },
    'user': {
        'read': ['public_kb', 'dept_{dept}'],     # 可读取 public 和本部门
        'write': [],                               # 无写入权限
        'delete': [],                              # 无删除权限
        'sync': [],                                # 无同步权限
        'create': False,
        'drop': False,
    }
}

# 公开知识库名称
PUBLIC_KB_NAME = 'public_kb'


def get_user_permissions(role: str) -> List[str]:
    """
    获取角色对应的可访问安全级别

    Args:
        role: 用户角色

    Returns:
        可访问的安全级别列表
    """
    return ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS.get(DEFAULT_ROLE, ['public']))


def map_role(external_role: str) -> str:
    """
    将外部角色映射为本地角色

    Args:
        external_role: 网关传入的角色名称

    Returns:
        本地角色名称
    """
    # 先查找映射表
    if external_role in ROLE_MAPPING:
        return ROLE_MAPPING[external_role]

    # 如果映射表中没有，检查是否是有效的本地角色
    if external_role in ROLE_PERMISSIONS:
        return external_role

    # 未知角色使用默认角色
    return DEFAULT_ROLE


def require_gateway_auth(f):
    """
    网关认证装饰器 - 从 Header 读取用户信息

    网关会在请求中注入以下 Header:
    - X-User-ID: 用户唯一标识 (必需)
    - X-User-Name: 用户名 (可选，默认空字符串)
    - X-User-Role: 用户角色 (可选，默认 user)
    - X-User-Department: 部门 (可选，默认空字符串)

    认证成功后，用户信息会附加到 request.current_user：
    {
        "user_id": "xxx",
        "username": "用户名",
        "role": "admin/manager/user",
        "department": "部门"
    }
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        print(f"[DEBUG require_gateway_auth] 被调用, 函数名: {f.__name__}")
        # 开发模式：允许通过 Header 模拟用户（无网关时测试用）
        dev_mode = os.environ.get('DEV_MODE', '').lower() == 'true'

        # 从 Header 读取用户信息
        user_id = request.headers.get('X-User-ID')
        username = request.headers.get('X-User-Name', '')
        role = request.headers.get('X-User-Role', '')
        department = request.headers.get('X-User-Department', '')

        print(f"[DEBUG auth_gateway] user_id={user_id}, dev_mode={dev_mode}")

        # 开发模式下，如果没有 Header，使用默认测试用户
        if dev_mode and not user_id:
            user_id = 'dev-user'
            username = '开发测试用户'
            role = 'admin'
            department = '开发部'

        # 生产模式：必须有用户 ID
        if not user_id:
            print(f"[DEBUG auth_gateway] 认证失败: 缺少 user_id")
            return jsonify({
                "error": "缺少用户信息",
                "message": "请通过网关访问，或设置 DEV_MODE=true 进行开发测试"
            }), 401

        # 角色映射
        mapped_role = map_role(role) if role else DEFAULT_ROLE

        # 将用户信息附加到 request 对象
        request.current_user = {
            "user_id": user_id,
            "username": username,
            "role": mapped_role,
            "department": department
        }

        print(f"[DEBUG auth_gateway] set current_user={request.current_user}")

        return f(*args, **kwargs)

    return decorated


def require_role(*roles):
    """
    角色验证装饰器 - 需要指定角色才能访问

    必须与 @require_gateway_auth 一起使用，放在其后：

    使用方式：
        @app.route('/admin')
        @require_gateway_auth
        @require_role('admin')
        def admin_only():
            ...

        @app.route('/management')
        @require_gateway_auth
        @require_role('admin', 'manager')
        def management():
            ...

    Args:
        *roles: 允许访问的角色列表
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(request, 'current_user', None)

            if not user:
                return jsonify({
                    "error": "请先认证",
                    "message": "此接口需要认证，请确保请求经过网关"
                }), 401

            if user.get('role') not in roles:
                return jsonify({
                    "error": "权限不足",
                    "message": f"此接口需要以下角色之一: {', '.join(roles)}",
                    "your_role": user.get('role')
                }), 403

            return f(*args, **kwargs)

        return decorated

    return decorator


def get_current_user() -> Optional[Dict]:
    """
    获取当前登录用户信息（便捷函数）

    Returns:
        用户信息字典，未认证返回 None
    """
    return getattr(request, 'current_user', None)


def is_admin() -> bool:
    """检查当前用户是否为管理员"""
    user = get_current_user()
    return user is not None and user.get('role') == 'admin'


def is_manager_or_above() -> bool:
    """检查当前用户是否为经理或以上级别"""
    user = get_current_user()
    return user is not None and user.get('role') in ('admin', 'manager')


# ==================== 向量库权限管理 ====================

def get_accessible_collections(
    role: str,
    department: str,
    operation: str = "read",
    all_collections: List[str] = None
) -> List[str]:
    """
    获取用户可访问的向量库列表

    Args:
        role: 用户角色
        department: 用户部门
        operation: 操作类型 (read/write/delete/sync)
        all_collections: 所有可用的向量库列表（用于 admin 通配符展开）

    Returns:
        可访问的向量库名称列表
    """
    permissions = COLLECTION_PERMISSIONS.get(role, COLLECTION_PERMISSIONS.get(DEFAULT_ROLE, {}))
    allowed = permissions.get(operation, [])

    if not allowed:
        return []

    # 处理通配符
    if '*' in allowed:
        if all_collections:
            return all_collections
        else:
            # 如果没有传入 all_collections，返回默认列表
            return [PUBLIC_KB_NAME] + [f"dept_{dept}" for dept in ['finance', 'hr', 'tech', 'operation', 'marketing']]

    # 处理部门变量替换
    result = []
    for coll in allowed:
        if '{dept}' in coll:
            # 替换为用户部门
            if department:
                result.append(coll.replace('{dept}', department))
        else:
            result.append(coll)

    return result


def check_collection_permission(
    role: str,
    department: str,
    collection_name: str,
    operation: str = "read",
    all_collections: List[str] = None
) -> bool:
    """
    检查用户对向量库的操作权限

    Args:
        role: 用户角色
        department: 用户部门
        collection_name: 向量库名称
        operation: 操作类型 (read/write/delete/sync)
        all_collections: 所有可用的向量库列表

    Returns:
        是否有权限
    """
    accessible = get_accessible_collections(role, department, operation, all_collections)
    return collection_name in accessible


def can_create_collection(role: str) -> bool:
    """检查用户是否可以创建向量库"""
    permissions = COLLECTION_PERMISSIONS.get(role, {})
    return permissions.get('create', False)


def can_delete_collection(role: str) -> bool:
    """检查用户是否可以删除向量库"""
    permissions = COLLECTION_PERMISSIONS.get(role, {})
    return permissions.get('drop', False)


def require_collection_permission(operation: str):
    """
    向量库权限验证装饰器

    使用方式：
        @app.route('/documents/upload', methods=['POST'])
        @require_gateway_auth
        @require_collection_permission('write')
        def upload_document():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(request, 'current_user', None)
            if not user:
                return jsonify({
                    "error": "请先认证",
                    "message": "此接口需要认证"
                }), 401

            # 从请求中获取目标向量库名称
            collection_name = None

            # 尝试从 JSON body 获取
            if request.is_json:
                collection_name = request.json.get('collection') or request.json.get('kb_name')

            # 尝试从 form data 获取
            if not collection_name and request.form:
                collection_name = request.form.get('collection') or request.form.get('kb_name')

            # 尝试从 URL 参数获取
            if not collection_name:
                collection_name = request.args.get('collection') or request.args.get('kb_name')

            # 尝试从路径参数获取（如 /documents/<collection>/<path>）
            if not collection_name and 'collection' in kwargs:
                collection_name = kwargs.get('collection')

            if not collection_name:
                return jsonify({
                    "error": "缺少向量库参数",
                    "message": "请指定要操作的向量库 (collection 参数)"
                }), 400

            # 检查权限
            if not check_collection_permission(
                user['role'],
                user.get('department', ''),
                collection_name,
                operation
            ):
                return jsonify({
                    "error": "权限不足",
                    "message": f"您没有权限对此向量库执行 '{operation}' 操作",
                    "your_role": user['role'],
                    "your_department": user.get('department', ''),
                    "target_collection": collection_name,
                    "required_operation": operation
                }), 403

            # 将目标向量库附加到 request
            request.target_collection = collection_name

            return f(*args, **kwargs)

        return decorated

    return decorator


# ==================== 兼容旧代码 ====================

# 为了兼容使用旧 auth.py 的代码，提供别名
require_auth = require_gateway_auth
AuthManager = None  # 不再需要，保留引用避免导入错误


def get_auth_manager():
    """
    兼容旧代码 - 不再需要 AuthManager

    Returns:
        None (保留此函数是为了兼容旧代码中的 auth_manager.get_user_permissions() 调用)
    """
    return _FakeAuthManager()


class _FakeAuthManager:
    """兼容旧代码的假 AuthManager"""

    @staticmethod
    def get_user_permissions(role: str) -> List[str]:
        """获取用户权限"""
        return get_user_permissions(role)

    @staticmethod
    def get_accessible_collections(role: str, department: str) -> List[str]:
        """兼容旧代码 - 获取可访问的向量库"""
        return get_accessible_collections(role, department)
