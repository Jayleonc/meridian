"""
glog.sh 适配器

封装对 /data/pinfire/tools/glog.sh 的调用，用于按 request_id 搜索日志。
glog.sh 是服务器上的原生工具，能跨所有服务搜索指定 request_id 的日志。
"""

import asyncio
import re

from app.core.config import settings

# 输入安全校验：只允许字母数字和 ._- 字符
SAFE_INPUT = re.compile(r"^[a-zA-Z0-9._\-]{1,256}$")


def _validate_input(value: str) -> str:
    """校验输入，防止命令注入"""
    if not SAFE_INPUT.match(value):
        raise ValueError(f"输入包含不安全字符: {value!r}")
    return value


async def glog_search(request_id: str, back_hours: int = 0) -> str:
    """
    调用 glog.sh 搜索指定 request_id 的所有日志。

    返回原始文本输出，由调用方负责解析。
    """
    _validate_input(request_id)
    glog_path = settings.paths.glog_path

    cmd = [glog_path]
    if back_hours > 0:
        cmd.extend(["-b", str(back_hours)])
    cmd.append(request_id)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.limits.command_timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"glog.sh 超时 ({settings.limits.command_timeout_seconds}s)")

    return stdout.decode("utf-8", errors="replace")
