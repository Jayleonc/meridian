"""
FastAPI 应用入口

挂载 HTTP 路由和 MCP 传输层。
"""

import logging

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.logs import router as logs_router
from app.mcp.sse import messages_app as mcp_sse_messages_app
from app.mcp.sse import router as mcp_router

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def create_app() -> FastAPI:
    app = FastAPI(
        title="probe",
        version="0.2.0",
        description="MCP 日志排障服务器",
    )

    # 根路径 —— 避免爬虫/探活返回 404
    @app.get("/")
    async def root():
        return {
            "name": "probe",
            "version": "0.2.0",
            "mcp_sse": "/mcp/sse",
            "mcp_stream": "/mcp/stream",
            "health": "/health",
        }

    app.include_router(health_router)
    app.include_router(logs_router, prefix="/api")
    app.include_router(mcp_router, prefix="/mcp")
    app.mount("/mcp/messages/", mcp_sse_messages_app)

    return app


app = create_app()
