"""Atlas — Stdio 传输入口（供 Claude Code 等 MCP 客户端直连）"""

import asyncio

from app.adapters import pg_adapter
from app.adapters.mysql_adapter import close_pool, init_pool
from app.mcp.server import mcp


async def _run() -> None:
    await init_pool()
    await pg_adapter.init_pool()
    try:
        await mcp.run_async()
    finally:
        await pg_adapter.close_pool()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_run())
