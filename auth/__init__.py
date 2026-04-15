"""
认证与安全模块

包含：
- gateway: 网关认证、角色权限、向量库权限管理
- security: Prompt 注入防护、输入验证、输出过滤
"""

from auth.gateway import (
    require_gateway_auth,
    require_role,
    get_user_permissions,
    get_current_user,
    get_auth_manager,
    get_accessible_collections,
    check_collection_permission,
    can_create_collection,
    can_delete_collection,
    require_collection_permission,
    map_role,
    is_admin,
    is_manager_or_above,
)

from auth.security import (
    validate_query,
    sanitize_user_input,
    filter_response,
    is_safe_response,
    AgentConstraints,
)

__all__ = [
    # gateway
    'require_gateway_auth', 'require_role', 'get_user_permissions',
    'get_current_user', 'get_auth_manager',
    'get_accessible_collections', 'check_collection_permission',
    'can_create_collection', 'can_delete_collection',
    'require_collection_permission', 'map_role',
    'is_admin', 'is_manager_or_above',
    # security
    'validate_query', 'sanitize_user_input', 'filter_response',
    'is_safe_response', 'AgentConstraints',
]
