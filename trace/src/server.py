"""Trace — 链路关联 MCP"""

import logging

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

VERSION = "0.1.0"

app = FastAPI(
    title="Meridian Trace",
    version=VERSION,
    description="Meridian Trace service placeholder",
)

mcp = FastMCP("trace")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "trace",
        "version": VERSION,
        "health": "/health",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "trace"}


@mcp.tool()
async def search(
    trace_id: str | None = None,
    service: str | None = None,
    operation: str | None = None,
    min_duration: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict]:
    """搜索链路"""
    # TODO: 实现链路搜索
    return []


@mcp.tool()
async def get_topology(service: str | None = None, depth: int = 2) -> dict:
    """获取服务拓扑图"""
    # TODO: 实现拓扑查询
    return {"nodes": [], "edges": []}


@mcp.tool()
async def analyze(trace_id: str) -> dict:
    """分析链路性能瓶颈"""
    # TODO: 实现性能分析
    return {"trace_id": trace_id, "bottleneck": []}
