"""
文本脱敏工具

对日志中的敏感信息（手机号、身份证、token 等）进行脱敏处理。
"""

import re

REDACT_PATTERNS = [
    # token/密钥类
    (re.compile(r"(token|access_key|secret_key|cookie)\s*[=:]\s*\S+", re.IGNORECASE), r"\1=***REDACTED***"),
    # 手机号
    (re.compile(r"1[3-9]\d{9}"), "***PHONE***"),
    # 身份证号
    (re.compile(r"\d{17}[\dXx]"), "***ID_CARD***"),
]


def redact_text(text: str) -> str:
    """对单行文本做脱敏"""
    for pattern, replacement in REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_lines(lines: list[str]) -> list[str]:
    """批量脱敏"""
    return [redact_text(line) for line in lines]
