"""Nexus — MCP 网关.

当前 MVP 目标：让 Agent 只连接 Nexus，就能调用已可用的 Probe 能力。
Nexus 自己作为 MCP Server 暴露 `probe.*` 工具，内部通过 Probe 的 HTTP API 转发。
"""

import json
import logging
import os
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import FileResponse, Response

from src.agent import create_chat_router
from src.agent.sessions import HybridSessionStore
from src import devops

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

VERSION = "0.1.0"
DEFAULT_TIMEOUT = float(os.getenv("NEXUS_SERVICE_TIMEOUT", "30"))
RESERVED_FRONTEND_PREFIXES = {
    "api",
    "svc",
    "mcp",
    "health",
    "registry",
}


def _base_url(env_name: str, default: str) -> str:
    return os.getenv(env_name, default).rstrip("/")


PROBE_URL = _base_url("PROBE_URL", "http://127.0.0.1:3002")
ATLAS_URL = _base_url("ATLAS_URL", "http://127.0.0.1:3001")
LENS_URL = _base_url("LENS_URL", "http://127.0.0.1:3003")
TRACE_URL = _base_url("TRACE_URL", "http://127.0.0.1:3004")
chat_session_store = HybridSessionStore()

_registry: dict[str, dict[str, Any]] = {
    "atlas": {
        "name": "atlas",
        "version": "0.1.0",
        "base_url": ATLAS_URL,
        "health": "/health",
        "api_prefix": "/api",
        "mcp": {
            "sse": "/mcp/sse",
            "messages": "/mcp/messages/",
            "stream": "/mcp/stream/",
        },
        "tools": [],
    },
    "probe": {
        "name": "probe",
        "version": "0.2.0",
        "base_url": PROBE_URL,
        "health": "/health",
        "api_prefix": "/api/logs",
        "mcp": {
            "sse": "/mcp/sse",
            "messages": "/mcp/messages/",
            "stream": "/mcp/stream/",
        },
        "tools": [
            "probe.search_by_request_id",
            "probe.search_logs",
            "probe.tail_errors",
            "probe.tail_service_logs",
            "probe.list_services",
            "probe.context_around_match",
        ],
    },
    "lens": {
        "name": "lens",
        "version": "0.1.0",
        "base_url": LENS_URL,
        "health": "/health",
        "api_prefix": "/api",
        "mcp": {
            "sse": "/mcp/sse",
            "messages": "/mcp/messages/",
            "stream": "/mcp/stream/",
        },
        "tools": [],
    },
    "trace": {
        "name": "trace",
        "version": "0.1.0",
        "base_url": TRACE_URL,
        "health": "/health",
        "api_prefix": "/api",
        "mcp": {
            "sse": "/mcp/sse",
            "messages": "/mcp/messages/",
            "stream": "/mcp/stream/",
        },
        "tools": [],
    }
}

mcp = FastMCP("nexus")
sse_transport = SseServerTransport("/mcp/messages/")
session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=True,
)


class StreamableHTTPApp:
    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        await session_manager.handle_request(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await chat_session_store.init()
    try:
        async with session_manager.run():
            yield
    finally:
        await chat_session_store.close()


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _console_dist_dir() -> Path:
    configured = os.getenv("CONSOLE_DIST_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "console" / "dist"


def _nexus_info() -> dict[str, Any]:
    return {
        "name": "nexus",
        "version": VERSION,
        "mcp_sse": "/mcp/sse",
        "mcp_stream": "/mcp/stream/",
        "health": "/health",
        "registry": "/registry",
        "chat": "/api/chat",
        "console": "/",
        "devops": {
            "enabled": devops.is_enabled(),
            "status": "/api/devops/status",
            "logs": "/api/devops/logs",
            "tools": [
                "devops.runtime_status",
                "devops.list_service_logs",
                "devops.tail_service_log",
                "devops.config_check",
                "devops.smoke_test",
                "devops.console_status",
            ],
        },
    }


async def _request_service(
    service: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    base_url = _registry[service]["base_url"]
    url = f"{base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.request(method, url, params=params, json=json_body)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {"status": "ok"}
    except httpx.HTTPStatusError as exc:
        return {
            "error": "downstream_http_error",
            "service": service,
            "status_code": exc.response.status_code,
            "body": exc.response.text[:500],
        }
    except httpx.RequestError as exc:
        return {
            "error": "downstream_unavailable",
            "service": service,
            "detail": str(exc),
        }


async def _probe(method: str, path: str, **kwargs: Any) -> Any:
    return await _request_service("probe", method, path, **kwargs)


async def _downstream_health() -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = {}
    for name, svc in _registry.items():
        result = await _request_service(name, "GET", svc["health"])
        ok = not (isinstance(result, dict) and result.get("error"))
        services[name] = {"status": "ok" if ok else "down", "detail": result}
    return services


async def _devops_runtime_status() -> dict[str, Any]:
    console = devops.console_status(_console_dist_dir())
    downstream = await _downstream_health()
    return devops.runtime_status(
        downstream=downstream,
        nexus=_nexus_info(),
        console=console,
    )


async def _devops_smoke_result() -> dict[str, Any]:
    console = devops.console_status(_console_dist_dir())
    downstream = await _downstream_health()
    return devops.smoke_result(downstream=downstream, console=console)


def _devops_disabled() -> dict[str, Any]:
    return {
        "error": "devops_disabled",
        "detail": "set MERIDIAN_DEVOPS_ENABLED=true when starting Nexus to expose read-only DevOps tools",
    }


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


async def _call_chat_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "probe_search_by_request_id":
        request_id = str(args["request_id"])
        return await _probe(
            "GET",
            f"/api/logs/trace/{quote(request_id, safe='')}",
            params=_clean_params(
                {
                    "back_hours": args.get("back_hours", 0),
                    "hint_time": args.get("hint_time"),
                }
            ),
        )

    if name == "probe_search_logs":
        return await _probe(
            "POST",
            "/api/logs/search",
            json_body={
                "keyword": args["keyword"],
                "service": args.get("service"),
                "start_time": args.get("start_time"),
                "end_time": args.get("end_time"),
                "level": args.get("level"),
                "limit": args.get("limit", 20),
            },
        )

    if name == "probe_tail_errors":
        return await _probe(
            "GET",
            "/api/logs/errors",
            params=_clean_params(
                {
                    "hours_back": args.get("hours_back", 1),
                    "service": args.get("service"),
                    "keyword": args.get("keyword"),
                    "limit": args.get("limit", 30),
                }
            ),
        )

    if name == "probe_tail_service_logs":
        service = str(args["service"])
        return await _probe(
            "GET",
            f"/api/logs/services/{quote(service, safe='')}/tail",
            params=_clean_params(
                {
                    "hours_back": args.get("hours_back", 1),
                    "level": args.get("level"),
                    "keyword": args.get("keyword"),
                    "limit": args.get("limit", 50),
                }
            ),
        )

    if name == "probe_list_services":
        return await _probe("GET", "/api/logs/services")

    if name == "probe_context_around_match":
        return await _probe(
            "GET",
            "/api/logs/context",
            params={
                "file": args["file"],
                "line_number": args["line_number"],
                "before": args.get("before", 10),
                "after": args.get("after", 10),
            },
        )

    return {"error": "unknown_tool", "tool": name}


def _forward_headers(headers: httpx.Headers) -> dict[str, str]:
    excluded = {
        "connection",
        "content-encoding",
        "content-length",
        "transfer-encoding",
    }
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in excluded
    }


async def _proxy_request(
    request: Request,
    service: str,
    path: str,
    *,
    upstream_prefix: str,
) -> Response:
    if service not in _registry:
        return Response(
            content=_json({"error": f"Unknown service: {service}"}),
            status_code=404,
            media_type="application/json",
        )

    upstream_path = f"{upstream_prefix.rstrip('/')}/{path.lstrip('/')}"
    if not path:
        upstream_path = upstream_prefix or "/"
    url = f"{_registry[service]['base_url']}{upstream_path}"

    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.request(
                request.method,
                url,
                params=request.query_params,
                content=body,
                headers=headers,
            )
    except httpx.RequestError as exc:
        return Response(
            content=_json(
                {
                    "error": "downstream_unavailable",
                    "service": service,
                    "detail": str(exc),
                }
            ),
            status_code=502,
            media_type="application/json",
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_forward_headers(resp.headers),
    )


@mcp.tool(name="probe.search_by_request_id")
async def probe_search_by_request_id(
    request_id: str,
    back_hours: int = 0,
    hint_time: str | None = None,
) -> str:
    """通过 Probe 按 request_id 追踪完整日志链路。"""
    data = await _probe(
        "GET",
        f"/api/logs/trace/{quote(request_id, safe='')}",
        params={"back_hours": back_hours, "hint_time": hint_time},
    )
    return _json(data)


@mcp.tool(name="probe.search_logs")
async def probe_search_logs(
    keyword: str,
    service: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    level: str | None = None,
    limit: int = 20,
) -> str:
    """通过 Probe 按关键词搜索日志。"""
    data = await _probe(
        "POST",
        "/api/logs/search",
        json_body={
            "keyword": keyword,
            "service": service,
            "start_time": start_time,
            "end_time": end_time,
            "level": level,
            "limit": limit,
        },
    )
    return _json(data)


@mcp.tool(name="probe.tail_errors")
async def probe_tail_errors(
    hours_back: int = 1,
    service: str | None = None,
    keyword: str | None = None,
    limit: int = 30,
) -> str:
    """通过 Probe 查看最近错误日志。"""
    data = await _probe(
        "GET",
        "/api/logs/errors",
        params=_clean_params(
            {"hours_back": hours_back, "service": service, "keyword": keyword, "limit": limit}
        ),
    )
    return _json(data)


@mcp.tool(name="probe.tail_service_logs")
async def probe_tail_service_logs(
    service: str,
    hours_back: int = 1,
    level: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> str:
    """通过 Probe 按服务查看最近日志。"""
    data = await _probe(
        "GET",
        f"/api/logs/services/{quote(service, safe='')}/tail",
        params=_clean_params(
            {
                "hours_back": hours_back,
                "level": level,
                "keyword": keyword,
                "limit": limit,
            }
        ),
    )
    return _json(data)


@mcp.tool(name="probe.list_services")
async def probe_list_services() -> str:
    """通过 Probe 列出当前环境可观测服务。"""
    data = await _probe("GET", "/api/logs/services")
    return _json(data)


@mcp.tool(name="probe.context_around_match")
async def probe_context_around_match(
    file: str,
    line_number: int,
    before: int = 10,
    after: int = 10,
) -> str:
    """通过 Probe 获取某条日志命中行的上下文。"""
    data = await _probe(
        "GET",
        "/api/logs/context",
        params={
            "file": file,
            "line_number": line_number,
            "before": before,
            "after": after,
        },
    )
    return _json(data)


@mcp.tool(name="devops.runtime_status")
async def devops_runtime_status() -> str:
    """查看 Meridian 开发环境运行状态、下游健康、Console 静态资源和日志文件位置。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    return _json(await _devops_runtime_status())


@mcp.tool(name="devops.list_service_logs")
async def devops_list_service_logs() -> str:
    """列出 dev-server 为 Nexus/Atlas/Probe/Lens/Trace 落盘的服务日志文件。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    return _json(devops.service_log_summary())


@mcp.tool(name="devops.tail_service_log")
async def devops_tail_service_log(service: str, lines: int = 120) -> str:
    """读取指定 Meridian 服务最近的运行日志。service 可选 nexus/atlas/probe/lens/trace。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    try:
        return _json(devops.tail_service_log(service, lines))
    except ValueError as exc:
        return _json({"error": "invalid_service", "detail": str(exc)})


@mcp.tool(name="devops.config_check")
async def devops_config_check() -> str:
    """检查开发环境关键配置是否存在，不返回 API key 等敏感值。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    return _json(devops.config_check())


@mcp.tool(name="devops.smoke_test")
async def devops_smoke_test() -> str:
    """执行只读 smoke test：检查 Console 构建、日志目录和下游服务健康。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    return _json(await _devops_smoke_result())


@mcp.tool(name="devops.console_status")
async def devops_console_status() -> str:
    """查看 Nexus 正在托管的 Console 静态资源状态。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    return _json(devops.console_status(_console_dist_dir()))


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meridian Nexus",
        version=VERSION,
        description="Meridian MCP gateway",
        lifespan=lifespan,
    )
    console_dist = _console_dist_dir()
    console_index = console_dist / "index.html"
    console_enabled = console_index.exists()

    @app.get("/")
    async def root():
        if console_enabled:
            return FileResponse(console_index)
        return _nexus_info()

    @app.get("/api/nexus")
    async def nexus_info():
        return _nexus_info()

    @app.get("/health")
    async def health():
        services = await _downstream_health()
        overall = "ok"
        for detail in services.values():
            if detail["status"] != "ok":
                overall = "degraded"
        return {"status": overall, "service": services}

    @app.get("/registry")
    async def registry():
        return {"service": list(_registry.values())}

    @app.get("/api/devops/status")
    async def devops_status_api():
        if not devops.is_enabled():
            return _devops_disabled()
        return await _devops_runtime_status()

    @app.get("/api/devops/logs")
    async def devops_logs_api():
        if not devops.is_enabled():
            return _devops_disabled()
        return devops.service_log_summary()

    @app.get("/api/devops/logs/{service}")
    async def devops_tail_log_api(service: str, lines: int = 120):
        if not devops.is_enabled():
            return _devops_disabled()
        try:
            return devops.tail_service_log(service, lines)
        except ValueError as exc:
            return {"error": "invalid_service", "detail": str(exc)}

    @app.get("/api/devops/config")
    async def devops_config_api():
        if not devops.is_enabled():
            return _devops_disabled()
        return devops.config_check()

    @app.get("/api/devops/smoke")
    async def devops_smoke_api():
        if not devops.is_enabled():
            return _devops_disabled()
        return await _devops_smoke_result()

    app.include_router(
        create_chat_router(_call_chat_tool, chat_session_store),
        prefix="/api/chat",
        tags=["Chat"],
    )

    @app.api_route(
        "/api/{service}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy_api_root(request: Request, service: str):
        return await _proxy_request(
            request,
            service,
            "",
            upstream_prefix="/api",
        )

    @app.api_route(
        "/api/{service}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy_api(request: Request, service: str, path: str):
        return await _proxy_request(
            request,
            service,
            path,
            upstream_prefix="/api",
        )

    @app.api_route(
        "/svc/{service}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy_svc_root(request: Request, service: str):
        return await _proxy_request(
            request,
            service,
            "",
            upstream_prefix="",
        )

    @app.api_route(
        "/svc/{service}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy_svc(request: Request, service: str, path: str):
        return await _proxy_request(
            request,
            service,
            path,
            upstream_prefix="",
        )

    mcp_router = APIRouter(tags=["MCP"])

    @mcp_router.get("/sse")
    async def handle_sse(request: Request):
        server = mcp._mcp_server
        async with sse_transport.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
        return Response()

    app.include_router(mcp_router, prefix="/mcp")
    app.mount("/mcp/messages/", sse_transport.handle_post_message)
    app.mount("/mcp/stream", StreamableHTTPApp())

    if console_enabled:
        assets_dir = console_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="console-assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def console_spa_fallback(path: str):
            first = path.split("/", 1)[0]
            if first in RESERVED_FRONTEND_PREFIXES:
                return Response(
                    content=_json({"error": "not_found", "path": f"/{path}"}),
                    status_code=404,
                    media_type="application/json",
                )
            return FileResponse(console_index)

    return app


app = create_app()
