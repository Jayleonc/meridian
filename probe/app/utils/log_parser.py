"""
日志行解析器

将 Brick 微服务框架产生的结构化日志行解析为字典。
格式示例: UNKNOWN(9827,6062) 03-02T12:11:20.5801 <SnWCax0iwhiYZPO4RNsA.NWtYBR> INF impl/topic.go:363:..func message
"""

import re

from app.core.config import settings

# Brick 微服务日志正则
LOG_PATTERN = re.compile(
    r"^(\w+)\((\d+),(\d+)\)\s+"           # 进程名(pid,tid)
    r"(\d{2}-\d{2}T[\d:.]+)\s+"           # 时间戳 MM-DDThh:mm:ss.ssss
    r"(?:<([^>]+)>\s+)?"                   # 可选的 <request_id>
    r"(?:\x1b\[\d+m)?"                     # 可选的 ANSI 颜色码开头
    r"(INF|WAR|ERR|DBG|IMP)\s+"            # 日志级别（IMP=Important，比ERR更严重的最终失败）
    r"(\S+)"                               # 来源 file:line:func
    r"(?:\x1b\[0m)?"                       # 可选的 ANSI 颜色码结尾
    r"\s+(.*)"                             # 消息正文
)

# ANSI 转义序列清理
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _truncate(text: str, max_len: int = 0) -> str:
    """截断过长的文本，避免 req/resp body 等超长内容浪费 token"""
    if max_len <= 0:
        max_len = settings.limits.max_line_length
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"...[截断, 原始 {len(text)} 字符]"


def _strip_rpc_body(text: str) -> str:
    """
    从 RPC 日志消息中去掉 req {...} 和 rsp {...} 的具体内容，
    只保留 req{...} / rsp{...} 的占位标记和其他关键字段（path, code, time）。

    示例输入:
      ctx xxx path /hlopen/CsContactApplyEvent code -21 req {"big":"json"} rsp {"also":"big"} time 5
    示例输出:
      ctx xxx path /hlopen/CsContactApplyEvent code -21 req{..} rsp{..} time 5
    """
    if 'req ' not in text and 'rsp ' not in text:
        return text

    result = []
    i = 0
    length = len(text)

    while i < length:
        # 检查是否匹配 req { 或 rsp {
        if i < length - 4 and text[i:i+4] in ('req ', 'rsp '):
            tag = text[i:i+3]  # 'req' or 'rsp'
            j = i + 4
            # 跳过空白
            while j < length and text[j] == ' ':
                j += 1
            if j < length and text[j] == '{':
                # 用花括号计数找到匹配的 }
                depth = 1
                k = j + 1
                while k < length and depth > 0:
                    if text[k] == '{':
                        depth += 1
                    elif text[k] == '}':
                        depth -= 1
                    k += 1
                result.append(f'{tag}{{..}}')
                i = k
                continue
        result.append(text[i])
        i += 1

    return ''.join(result)


def _clean_ansi(text: str) -> str:
    """去除 ANSI 颜色转义序列"""
    return ANSI_ESCAPE.sub("", text)


def parse_log_line(line: str) -> dict | None:
    """
    解析单行日志，返回结构化字典；无法解析则返回 None。
    解析后的 message 会自动截断。
    """
    cleaned = _clean_ansi(line.strip())
    m = LOG_PATTERN.match(cleaned)
    if not m:
        return None
    return {
        "process": m.group(1),
        "pid": m.group(2),
        "tid": m.group(3),
        "timestamp": m.group(4),
        "request_id": m.group(5),
        "level": m.group(6),
        "source": m.group(7),
        "message": _truncate(m.group(8)),
    }
