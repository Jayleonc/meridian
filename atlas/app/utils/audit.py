"""
审计日志模块

每次工具调用后写一条 JSON Lines 记录，包含工具名、参数、结果摘要、耗时。
优先写入 PG audit_log 表（复用 pg_adapter），同时写入本地文件作为兜底。
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from app.core.config import get_settings

logger = logging.getLogger("atlas.audit")


def _write_to_file(entry: dict) -> None:
    """写一条 JSON Line 到审计日志文件。"""
    path = get_settings().server.audit_log_path
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[audit] 文件写入失败: {e}", file=sys.stderr)


async def audit_log(
    tool: str,
    params: dict,
    result_summary: str = "",
    duration_ms: int = 0,
) -> None:
    """记录一条审计日志。优先写 PG，同时写本地文件兜底。"""
    now = datetime.now(timezone.utc)
    entry = {
        "time": now.isoformat(),
        "tool": tool,
        "params": params,
        "result_summary": result_summary,
        "duration_ms": duration_ms,
    }

    # 始终写文件
    _write_to_file(entry)

    # 复用 pg_adapter 写 PG
    from app.adapters.pg_adapter import save_audit_log

    try:
        await save_audit_log(
            tool_name=tool,
            parameter=params,
        )
    except Exception as e:
        logger.warning("PG 审计写入失败: %s", e)


def _summarize_result(result: Any, max_len: int = 200) -> str:
    """从工具返回值中提取摘要。"""
    if result is None:
        return ""
    text = str(result)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def audited(tool_name: str | None = None) -> Callable:
    """装饰器：自动为 async 工具函数添加审计日志和计时。

    用法：
        @audited()
        async def my_tool(arg: str) -> str: ...

        @audited("custom_name")
        async def my_tool(arg: str) -> str: ...
    """

    def decorator(fn: Callable) -> Callable:
        name = tool_name or fn.__name__

        @wraps(fn)
        async def wrapper(*args, **kwargs) -> Any:
            start = time.monotonic()
            error_msg = ""
            result = None
            try:
                result = await fn(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                summary = error_msg if error_msg else _summarize_result(result)
                await audit_log(
                    tool=name,
                    params=kwargs if kwargs else {f"arg{i}": v for i, v in enumerate(args)},
                    result_summary=summary,
                    duration_ms=duration_ms,
                )

        return wrapper

    return decorator
