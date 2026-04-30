"""
统一响应格式工具

提供标准化的 API 响应格式：
- success_response: 成功响应
- error_response: 错误响应

所有响应自动包含 success 字段，保持向后兼容。
"""

from flask import jsonify
from typing import Any, Optional
from core.status_codes import get_status_message


def success_response(
    data: Any = None,
    status_code: int = 2000,
    message: Optional[str] = None,
    http_status: int = 200,
    **extra_fields
):
    """
    构造成功响应

    Args:
        data: 响应数据
        status_code: 业务状态码 (默认 2000)
        message: 自定义消息 (默认使用状态码对应描述)
        http_status: HTTP 状态码 (默认 200)
        **extra_fields: 额外字段

    Returns:
        Flask Response 对象
    """
    response = {
        "success": True,
        "status": "success",
        "status_code": status_code,
        "message": message or get_status_message(status_code),
    }

    if data is not None:
        response["data"] = data

    # 添加额外字段
    response.update(extra_fields)

    return jsonify(response), http_status


def error_response(
    error_code: str,
    status_code: int,
    message: str,
    http_status: int = 400,
    **extra_fields
):
    """
    构造错误响应

    Args:
        error_code: 错误码 (如 "MISSING_PARAMS", "UNAUTHORIZED")
        status_code: 业务状态码
        message: 错误消息
        http_status: HTTP 状态码 (默认 400)
        **extra_fields: 额外字段

    Returns:
        Flask Response 对象
    """
    response = {
        "success": False,
        "status": "failed",
        "error_code": error_code,
        "status_code": status_code,
        "message": message,
    }

    # 添加额外字段
    response.update(extra_fields)

    return jsonify(response), http_status
