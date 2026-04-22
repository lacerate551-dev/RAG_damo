"""
Prompt 注入防护模块 - 输入验证、查询隔离、输出过滤

功能：
1. 输入验证 - 检测注入模式、长度限制
2. 查询隔离 - XML 标签包裹用户输入，防止指令注入
3. 输出过滤 - 阻止敏感信息泄露
4. Agent 行为约束 - 调用次数上限、工具白名单

使用方式：
    from security import validate_query, sanitize_user_input, filter_response
"""

import re
import os
from typing import Tuple, Optional
from pathlib import Path


# ==================== 违禁词配置 ====================

# 违禁词文件路径
BANNED_WORDS_FILE = Path(__file__).parent.parent / "config" / "banned_words.txt"

def _load_banned_words() -> list:
    """从配置文件加载违禁词"""
    banned_words = []
    try:
        if BANNED_WORDS_FILE.exists():
            with open(BANNED_WORDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if line and not line.startswith('#'):
                        banned_words.append(line)
    except Exception as e:
        print(f"加载违禁词文件失败: {e}")
    return banned_words

# 加载违禁词列表
BANNED_WORDS = _load_banned_words()


# ==================== 输入验证 ====================

# 注入攻击常见模式
INJECTION_PATTERNS = [
    # 直接指令覆盖
    r"(?i)(ignore|forget|disregard|discard)\s+(previous|above|all|earlier|prior)\s+(instructions?|prompts?|rules?|context)",
    # 角色切换
    r"(?i)(you\s+are\s+now|act\s+as|pretend\s+to\s+be|roleplay|new\s+role)",
    # 系统提示词提取
    r"(?i)(show|display|print|output|reveal|tell)\s+me\s+(your|the)\s+(system\s+)?(prompt|instructions?|rules)",
    # 文档内容提取
    r"(?i)(output|print|display|show|list)\s+(all|every|complete|full)\s+(documents?|data|records?|files?|contents?)",
    # 系统指令标记
    r"(?i)system\s*[:：]\s*",
    # 配置信息提取
    r"(?i)(show|display|reveal)\s+(config|api\s*key|password|secret|credentials?)",
]

MAX_QUERY_LENGTH = 1000
MAX_CONVERSATION_LENGTH = 5000


def validate_query(query: str) -> Tuple[bool, str]:
    """
    验证用户查询是否安全

    Returns:
        (is_valid, reason)
    """
    if not query or not query.strip():
        return False, "查询内容不能为空"

    if len(query) > MAX_QUERY_LENGTH:
        return False, f"查询内容过长（最多{MAX_QUERY_LENGTH}字符）"

    # 检测违禁词
    for word in BANNED_WORDS:
        if word in query:
            return False, "查询包含违禁内容"

    # 检测注入模式
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query):
            return False, "查询包含不允许的内容"

    return True, ""


def sanitize_user_input(query: str) -> str:
    """
    将用户输入包裹在 XML 标签中，隔离指令注入

    LLM 在处理 <user_query> 标签内的内容时，
    应仅将其作为文本分析，不执行其中的指令。
    """
    # 移除可能破坏 XML 结构的字符
    cleaned = query.replace("<user_query>", "").replace("</user_query>", "")
    return f"<user_query>\n{cleaned}\n</user_query>"


def is_safe_response(response: str) -> Tuple[bool, Optional[str]]:
    """
    检查 LLM 输出是否包含敏感信息

    Returns:
        (is_safe, leaked_info_type or None)
    """
    sensitive_patterns = [
        (r"sk-[a-f0-9]{20,}", "API密钥"),
        (r"(?:password|密码)\s*[:：]\s*\S+", "密码"),
        (r"config\.(?:py|example)", "配置文件"),
        (r"(?:NEO4J_PASSWORD|JWT_SECRET)\s*=\s*\S+", "密钥配置"),
    ]

    for pattern, info_type in sensitive_patterns:
        if re.search(pattern, response, re.IGNORECASE):
            return False, info_type

    return True, None


def filter_response(response: str) -> str:
    """
    过滤 LLM 响应中的敏感信息（API密钥、密码等）
    """
    filtered = response

    replacements = [
        (r"sk-[a-f0-9]{20,}", "[已过滤]"),
        (r"(?:password|密码)\s*[:：]\s*\S+", "[已过滤]"),
        (r"config\.(?:py|example)", "[已过滤]"),
        (r"(?:NEO4J_PASSWORD|JWT_SECRET)\s*=\s*['\"]?\S+['\"]?", "[已过滤]"),
    ]

    for pattern, replacement in replacements:
        filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)

    return filtered


# ==================== Agent 行为约束 ====================

class AgentConstraints:
    """Agent 行为约束，防止恶意使用"""

    def __init__(
        self,
        max_iterations: int = 3,
        max_api_calls: int = 10,
        max_query_length: int = 1000,
        allowed_tools: set = None
    ):
        self.max_iterations = max_iterations
        self.max_api_calls = max_api_calls
        self.max_query_length = max_query_length
        self.allowed_tools = allowed_tools or {
            "kb_search", "web_search", "graph_search", "answer", "rewrite", "decompose"
        }
        self.api_calls = 0

    def check_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否在白名单中"""
        return tool_name in self.allowed_tools

    def check_budget(self) -> bool:
        """检查是否还有 API 调用预算"""
        self.api_calls += 1
        return self.api_calls <= self.max_api_calls

    def check_query_length(self, query: str) -> bool:
        """检查查询长度是否在限制内"""
        return len(query) <= self.max_query_length

    def reset(self):
        """重置调用计数（每次新请求开始时调用）"""
        self.api_calls = 0
