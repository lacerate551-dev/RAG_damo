"""
状态码定义

统一的业务状态码，用于 API 响应中标识操作结果。
状态码格式：4位数字，前两位表示类别，后两位表示具体状态
- 10xx: 处理中
- 20xx: 成功
- 40xx: 客户端错误
- 50xx: 服务端错误
"""

from typing import Dict

# 状态码到消息的映射
_STATUS_MESSAGES: Dict[int, str] = {
    # 处理中状态 (10xx)
    1000: "处理中",
    1001: "文件接收中",
    1002: "文件解析中",
    1003: "向量化中",
    1010: "同步进行中",
    1020: "出题生成中",
    1021: "批阅进行中",

    # 成功状态 (20xx)
    2000: "操作成功",
    2001: "创建成功",
    2002: "文件上传成功",
    2003: "批量上传完成",
    2004: "删除成功",
    2005: "更新成功",
    2010: "同步完成",
    2020: "出题成功",
    2021: "批阅完成",
    2030: "图片描述更新成功",

    # 客户端错误 (40xx)
    4000: "请求参数错误",
    4001: "未授权",
    4002: "禁止访问",
    4003: "资源不存在",
    4004: "没有上传文件",
    4005: "没有选择文件",
    4006: "请指定目标向量库",
    4007: "不支持的文件格式",
    4008: "文件大小超过限制",
    4009: "文档解析失败",
    4010: "文件不存在",
    4011: "向量库不存在",
    4012: "文件内容为空",
    4013: "权限不足",

    # 服务端错误 (50xx)
    5000: "服务器内部错误",
    5001: "服务不可用",
    5002: "向量化失败",
    5003: "LLM调用失败",
    5010: "同步失败",
    5020: "出题失败",
    5021: "批阅失败",
    5030: "图片描述更新失败",
}


def get_status_message(status_code: int) -> str:
    """
    根据状态码获取默认消息

    Args:
        status_code: 业务状态码

    Returns:
        状态码对应的默认消息
    """
    return _STATUS_MESSAGES.get(status_code, "未知状态")


# ==================== 常用状态码常量 ====================

# 处理中 (10xx)
PROCESSING = 1000
FILE_RECEIVING = 1001
FILE_PARSING = 1002
VECTORIZING = 1003
SYNC_RUNNING = 1010
EXAM_GENERATING = 1020
EXAM_GRADING = 1021

# 成功 (20xx)
SUCCESS = 2000
CREATED = 2001
UPLOAD_SUCCESS = 2002
BATCH_UPLOAD_SUCCESS = 2003
DELETE_SUCCESS = 2004
UPDATE_SUCCESS = 2005
SYNC_SUCCESS = 2010
EXAM_SUCCESS = 2020
GRADE_SUCCESS = 2021
IMAGE_DESC_SUCCESS = 2030

# 客户端错误 (40xx)
BAD_REQUEST = 4000
UNAUTHORIZED = 4001
FORBIDDEN = 4002
NOT_FOUND = 4003
NO_FILE = 4004
NO_FILE_SELECTED = 4005
NO_COLLECTION = 4006
UNSUPPORTED_FORMAT = 4007
FILE_TOO_LARGE = 4008
PARSE_ERROR = 4009
FILE_NOT_FOUND = 4010
COLLECTION_NOT_FOUND = 4011
NO_CONTENT = 4012
PERMISSION_DENIED = 4013

# 服务端错误 (50xx)
INTERNAL_ERROR = 5000
SERVICE_UNAVAILABLE = 5001
VECTORIZE_ERROR = 5002
LLM_ERROR = 5003
SYNC_ERROR = 5010
EXAM_ERROR = 5020
GRADE_ERROR = 5021
IMAGE_DESC_ERROR = 5030
