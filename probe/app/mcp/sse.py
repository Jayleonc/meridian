"""
MCP 传输层

同时支持两种传输协议：
1. SSE (Server-Sent Events) —— 当前 Claude Code 使用的方式
   - GET  /mcp/sse         建立 SSE 长连接
   - POST /mcp/messages/   发送 MCP 消息
2. StreamableHTTP —— 新一代协议，备用
   - POST/GET/DELETE /mcp/stream  统一端点
"""

from fastapi import APIRouter, Request
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import Response

from app.mcp.server import mcp

router = APIRouter(tags=["MCP"])

# ---- SSE 传输 ----
# 路径末尾带斜杠，与 FastAPI mount 路径一致，避免 307 重定向
sse_transport = SseServerTransport("/mcp/messages/")


@router.get("/sse")
async def handle_sse(request: Request):
    """SSE 连接端点"""
    server = mcp._mcp_server

    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )

    return Response()


# POST 消息处理器，挂载到 /mcp/messages/
messages_app = sse_transport.handle_post_message

# ---- StreamableHTTP 传输（备用）----
session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=True,
)


@router.api_route("/stream", methods=["GET", "POST", "DELETE"])
async def handle_streamable_http(request: Request):
    """StreamableHTTP 端点（备用）"""
    await session_manager.handle_request(
        request.scope, request.receive, request._send
    )
