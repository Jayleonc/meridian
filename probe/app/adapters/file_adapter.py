"""
文件适配器

提供对日志文件的安全读取操作：按时间定位文件、grep 搜索、上下文读取。
所有文件访问都经过白名单校验，防止路径穿越。
"""

import asyncio
import re
from collections import deque
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def _log_timezone() -> tzinfo:
    """返回业务日志文件名使用的时区。配置错误时使用本地时区兜底。"""
    try:
        return ZoneInfo(settings.time.log_timezone)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def get_hourly_files(start_time: datetime, end_time: datetime) -> list[Path]:
    """获取时间范围内的小时级日志文件列表"""
    log_dir = Path(settings.paths.hourly_log_dir)
    files = []
    current = start_time.replace(minute=0, second=0, microsecond=0)
    while current <= end_time:
        filename = current.strftime("%Y%m%d%H") + ".log"
        filepath = log_dir / filename
        if filepath.exists():
            files.append(filepath)
        current += timedelta(hours=1)
    return files


def get_recent_hourly_files(hours_back: int = 1) -> list[Path]:
    """获取最近 N 小时的日志文件"""
    now = datetime.now(_log_timezone())
    start = now - timedelta(hours=hours_back)
    return get_hourly_files(start, now)


async def grep_files(
    files: list[Path],
    pattern: str,
    max_lines: int = 50,
    extra_args: list[str] | None = None,
    from_end: bool = False,
    include_full_lines: bool = False,
) -> list[tuple[str, int, str]]:
    """
    在多个文件中 grep 搜索。

    返回: [(文件名, 行号, 行内容), ...]
    """
    if not files:
        return []

    cmd = ["grep", "-Hn"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(pattern)
    cmd.extend(str(f) for f in files)

    if from_end:
        return await _grep_files_from_end(
            files,
            pattern,
            max_lines,
            extra_args or [],
            include_full_lines=include_full_lines,
        )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.limits.command_timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError("grep 超时")

    results = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if len(results) >= max_lines:
            break
        parsed = _parse_grep_line(line, trim_line=not include_full_lines)
        if parsed:
            results.append(parsed)

    return results


async def _grep_files_from_end(
    files: list[Path],
    pattern: str,
    max_lines: int,
    extra_args: list[str],
    *,
    include_full_lines: bool = False,
) -> list[tuple[str, int, str]]:
    """用 grep 流式扫描并保留最后 N 条匹配。

    之前这里用 Python 逐行扫大日志文件，容易在开发服务器上超时并导致 500。
    grep 负责高性能匹配，Python 只保留最后 max_lines 条结果。
    """
    cmd = ["grep", "-Hn"]
    cmd.extend(extra_args)
    cmd.append(pattern)
    cmd.extend(str(f) for f in files)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def collect() -> list[tuple[str, int, str]]:
        assert proc.stdout is not None
        results: deque[tuple[str, int, str]] = deque(maxlen=max_lines)
        buffer = ""
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while True:
                newline = buffer.find("\n")
                if newline < 0:
                    break
                line = buffer[:newline].rstrip("\r")
                buffer = buffer[newline + 1:]
                parsed = _parse_grep_line(line, trim_line=not include_full_lines)
                if parsed:
                    results.append(parsed)

        if buffer:
            parsed = _parse_grep_line(buffer.rstrip("\r"), trim_line=not include_full_lines)
            if parsed:
                results.append(parsed)

        await proc.wait()
        return list(results)

    try:
        return await asyncio.wait_for(collect(), timeout=settings.limits.command_timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError("grep 超时")


def _parse_grep_line(line: str, *, trim_line: bool = True) -> tuple[str, int, str] | None:
    parts = line.split(":", 2)
    if len(parts) >= 3 and parts[1].isdigit():
        text = parts[2]
        return (parts[0], int(parts[1]), _trim_result_line(text) if trim_line else text)
    return None


def _scan_files_from_end(
    files: list[Path],
    pattern: str,
    max_lines: int,
    extra_args: list[str],
) -> list[tuple[str, int, str]]:
    matcher = _build_matcher(pattern, extra_args)
    results: deque[tuple[str, int, str]] = deque(maxlen=max_lines)
    for file in files:
        with file.open(encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.rstrip("\n")
                if matcher(text):
                    results.append((str(file), line_number, _trim_result_line(text)))
    return list(results)


def _build_matcher(pattern: str, extra_args: list[str]):
    if "-E" in extra_args or "-P" in extra_args:
        try:
            compiled = re.compile(pattern)
        except re.error:
            compiled = re.compile(re.escape(pattern))
        return compiled.search
    return lambda text: pattern in text


def _trim_result_line(text: str) -> str:
    max_len = max(settings.limits.max_line_length + 512, 2048)
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"...[截断, 原始 {len(text)} 字符]"


def _validate_file_path(file_path: str) -> Path:
    """校验文件路径是否在允许的目录下，防止路径穿越"""
    p = Path(file_path).resolve()
    allowed = [
        Path(settings.paths.hourly_log_dir).resolve(),
        Path(settings.paths.supervisor_log_dir).resolve(),
    ]
    for base in allowed:
        try:
            p.relative_to(base)
            return p
        except ValueError:
            continue
    raise ValueError(f"访问被拒绝: {file_path} 不在允许的目录内")


def read_context(file_path: str, line_number: int, before: int = 10, after: int = 10) -> dict:
    """读取指定行的上下文（前后各 N 行）"""
    p = _validate_file_path(file_path)

    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    start = max(1, line_number - before)
    end = line_number + after

    lines_before = []
    match_line = ""
    lines_after = []

    with open(p) as f:
        for i, line in enumerate(f, 1):
            if i < start:
                continue
            if i > end:
                break
            text = line.rstrip("\n")
            if i < line_number:
                lines_before.append(text)
            elif i == line_number:
                match_line = text
            else:
                lines_after.append(text)

    return {
        "before": lines_before,
        "match": match_line,
        "after": lines_after,
    }


def list_supervisor_services() -> list[str]:
    """列出 supervisor 管理的所有服务名"""
    sup_dir = Path(settings.paths.supervisor_log_dir)
    if not sup_dir.exists():
        return []

    services = set()
    for f in sup_dir.iterdir():
        name = f.name
        if "-stdout---supervisor-" in name:
            service = name.split("-stdout---supervisor-")[0]
            services.add(service)

    return sorted(services)
