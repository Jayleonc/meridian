"""
ops 聚合日志适配器。

这是 anlog.sh 生产适配的预备切片：只定义安全的结构化命令调用边界，
不把任意 shell 字符串暴露给 service / MCP / HTTP 调用方。
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

SAFE_HOST = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
SAFE_SERVICE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
MAX_KEYWORD_LENGTH = 256


@dataclass(slots=True)
class OpsHostOutput:
    host: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.returncode == 0


def validate_search_params(
    *,
    service: str,
    keyword: str,
    hours_back: int,
    hosts: list[str],
    limit: int,
) -> list[str]:
    """校验 ops 聚合查询参数，并返回去重后的 hosts。"""
    if not SAFE_SERVICE.fullmatch(service):
        raise ValueError(f"service 包含不安全字符或长度非法: {service!r}")

    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword 不能为空")
    if len(keyword) > MAX_KEYWORD_LENGTH:
        raise ValueError(f"keyword 超过长度上限 {MAX_KEYWORD_LENGTH}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in keyword):
        raise ValueError("keyword 不能包含控制字符")

    if hours_back < 1 or hours_back > settings.limits.max_time_range_hours:
        raise ValueError(
            f"hours_back 必须在 1 到 {settings.limits.max_time_range_hours} 之间"
        )
    if limit < 1 or limit > settings.limits.max_lines:
        raise ValueError(f"limit 必须在 1 到 {settings.limits.max_lines} 之间")

    normalized_hosts = _normalize_hosts(hosts)
    if len(normalized_hosts) > settings.ops.max_hosts:
        raise ValueError(f"hosts 数量 {len(normalized_hosts)} 超过上限 {settings.ops.max_hosts}")

    allowed = set(settings.ops.allowed_hosts)
    if not allowed:
        raise ValueError("ops.allowed_hosts 为空，不能执行 ops 聚合查询")
    blocked = [host for host in normalized_hosts if host not in allowed]
    if blocked:
        raise ValueError(f"host 不在 ops.allowed_hosts 白名单内: {', '.join(blocked)}")

    return normalized_hosts


async def search_ops_logs(
    *,
    service: str,
    keyword: str,
    hours_back: int,
    hosts: list[str],
    limit: int,
) -> list[OpsHostOutput]:
    """按 host 调用预配置 ops 聚合命令。

    当前约定的命令参数是预备接口，后续真实 anlog.sh 接入时可在本适配器内替换。
    """
    validated_hosts = validate_search_params(
        service=service,
        keyword=keyword,
        hours_back=hours_back,
        hosts=hosts,
        limit=limit,
    )
    command_path = _validate_command_path(settings.ops.command_path)

    tasks = [
        _run_host_search(
            command_path=command_path,
            host=host,
            service=service,
            keyword=keyword.strip(),
            hours_back=hours_back,
            limit=limit,
        )
        for host in validated_hosts
    ]
    return await asyncio.gather(*tasks)


def _normalize_hosts(hosts: list[str]) -> list[str]:
    if not hosts:
        raise ValueError("hosts 不能为空")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in hosts:
        host = raw.strip()
        if not SAFE_HOST.fullmatch(host):
            raise ValueError(f"host 包含不安全字符或长度非法: {raw!r}")
        if host not in seen:
            normalized.append(host)
            seen.add(host)
    return normalized


def _validate_command_path(command_path: str) -> str:
    path = Path(command_path)
    if not path.is_absolute():
        raise ValueError("ops.command_path 必须是绝对路径")
    if not path.exists():
        raise ValueError(f"ops.command_path 不存在: {command_path}")
    return str(path)


async def _run_host_search(
    *,
    command_path: str,
    host: str,
    service: str,
    keyword: str,
    hours_back: int,
    limit: int,
) -> OpsHostOutput:
    cmd = [
        command_path,
        "--host",
        host,
        "--service",
        service,
        "--keyword",
        keyword,
        "--hours-back",
        str(hours_back),
        "--limit",
        str(limit),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.ops.timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return OpsHostOutput(host=host, error=f"timeout after {settings.ops.timeout_seconds}s")

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        return OpsHostOutput(
            host=host,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=proc.returncode or 1,
            error=stderr_text or f"command exited with {proc.returncode}",
        )
    return OpsHostOutput(host=host, stdout=stdout_text, stderr=stderr_text)
