"""Nexus — MCP 网关.

当前 MVP 目标：让 Agent 只连接 Nexus，就能调用已可用的 Probe、Atlas、Lens 能力。
Nexus 自己作为 MCP Server 暴露受控工具，内部通过下游服务 HTTP API 转发。
"""

import json
import logging
import os
import re
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from pydantic import ValidationError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import FileResponse, Response

from src.agent import create_chat_router
from src.agent.tools import validate_tool_args
from src.agent.sessions import HybridSessionStore
from src import devops
from src.registry import load_tool_registry
from src.tool_gateway import ToolGateway

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

VERSION = "0.1.0"
DEFAULT_TIMEOUT = float(os.getenv("NEXUS_SERVICE_TIMEOUT", "30"))
TOOL_EXPOSURE_POLICY: dict[str, Any] = {
    "mode": "controlled_gateway",
    "transparent_downstream_mcp": False,
    "source": "nexus_registry_allowlist",
    "description": (
        "Nexus exposes only named, constrained tools declared by Nexus. "
        "Downstream MCP tools are not automatically or transparently exposed."
    ),
}
RESERVED_FRONTEND_PREFIXES = {
    "api",
    "svc",
    "mcp",
    "health",
    "registry",
}


chat_session_store = HybridSessionStore()
_registry = load_tool_registry()
_gateway = ToolGateway(_registry)
_dynamic_tools_registered: list[str] = []

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
        "tool_exposure": TOOL_EXPOSURE_POLICY,
        "mcp_sse": "/mcp/sse",
        "mcp_stream": "/mcp/stream/",
        "health": "/health",
        "registry": "/registry",
        "chat": "/api/chat",
        "diagnosis": {
            "request": "/api/diagnosis/request",
            "tools": ["meridian.diagnose_request"],
        },
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
                "devops.list_chat_sessions",
                "devops.search_chat_messages",
                "devops.get_chat_session",
            ],
        },
    }


def _registry_payload() -> dict[str, Any]:
    services: list[dict[str, Any]] = []
    for service in _registry.values():
        item = dict(service)
        item["mcp"] = dict(service["mcp"])
        item["tools"] = list(service["tools"])
        item["tool_exposure"] = {
            "source": TOOL_EXPOSURE_POLICY["source"],
            "transparent_downstream_mcp": TOOL_EXPOSURE_POLICY["transparent_downstream_mcp"],
        }
        services.append(item)
    return {
        "tool_exposure": TOOL_EXPOSURE_POLICY,
        "dynamic_tools_registered": list(_dynamic_tools_registered),
        "service": services,
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


async def _atlas(method: str, path: str, **kwargs: Any) -> Any:
    return await _request_service("atlas", method, path, **kwargs)


async def _lens(method: str, path: str, **kwargs: Any) -> Any:
    return await _request_service("lens", method, path, **kwargs)


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


def _service_matches_query(service: dict[str, Any], query: str) -> bool:
    text = json.dumps(service, ensure_ascii=False, default=str).lower()
    return query.lower() in text


_DIAGNOSIS_STOPWORDS = {
    "ctx",
    "err",
    "error",
    "fail",
    "failed",
    "false",
    "from",
    "http",
    "https",
    "info",
    "message",
    "nil",
    "path",
    "req",
    "request",
    "response",
    "rsp",
    "service",
    "timeout",
    "true",
    "warn",
}


async def _atlas_search_metadata(query: str) -> dict[str, Any]:
    metadata = await _atlas(
        "GET",
        "/api/schemas/search/meta",
        params={"q": query},
    )
    result = dict(metadata) if isinstance(metadata, dict) else {"metadata": metadata}

    services = await _atlas("GET", "/api/services")
    if isinstance(services, dict) and services.get("error"):
        result["matched_service"] = []
        result["service_search_error"] = services
        return result

    service_items = services.get("service", []) if isinstance(services, dict) else []
    result["matched_service"] = [
        service
        for service in service_items
        if isinstance(service, dict) and _service_matches_query(service, query)
    ][:20]
    return result


def _compact_list(value: Any, limit: int) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def _diagnosis_terms(trace: dict[str, Any], max_terms: int = 8) -> list[str]:
    terms: list[str] = []

    for service in _compact_list(trace.get("services"), 12):
        _append_diagnosis_term(terms, service)
    for suspect in _compact_list(trace.get("suspects"), 8):
        if isinstance(suspect, dict):
            _append_diagnosis_term(terms, suspect.get("service"))
            for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", str(suspect.get("message", ""))):
                _append_diagnosis_term(terms, token)
    for item in _compact_list(trace.get("errors"), 4) + _compact_list(trace.get("warns"), 2):
        if isinstance(item, dict):
            _append_diagnosis_term(terms, item.get("service"))
            for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", str(item.get("message", ""))):
                _append_diagnosis_term(terms, token)

    return terms[:max_terms]


def _append_diagnosis_term(terms: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    candidates = [text, *re.split(r"[^a-zA-Z0-9_]+", text)]
    for candidate in candidates:
        normalized = candidate.strip("_").lower()
        if len(normalized) < 3 or normalized in _DIAGNOSIS_STOPWORDS:
            continue
        if normalized not in terms:
            terms.append(normalized)


def _summarize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": trace.get("request_id"),
        "total_lines": trace.get("total_lines", 0),
        "time_range": trace.get("time_range", ""),
        "searched_hours": trace.get("searched_hours", 0),
        "services": _compact_list(trace.get("services"), 20),
        "error_count": trace.get("error_count", 0),
        "warn_count": trace.get("warn_count", 0),
        "service_stats": trace.get("service_stats", {}),
        "suspects": _compact_list(trace.get("suspects"), 8),
        "errors": _compact_list(trace.get("errors"), 8),
        "warns": _compact_list(trace.get("warns"), 5),
        "hint": trace.get("hint", ""),
        "next_actions": trace.get("next_actions", []),
    }


def _entity_score(entity: dict[str, Any], terms: list[str]) -> int:
    text = " ".join(
        str(entity.get(key, ""))
        for key in ("name", "display_name", "database", "db_type")
    ).lower()
    return sum(3 if term in text else 0 for term in terms)


def _summarize_entity_detail(detail: Any) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {"error": "invalid_entity_detail", "detail": detail}
    fields = detail.get("fields") if isinstance(detail.get("fields"), dict) else {}
    field_items = []
    for name, field in list(fields.items())[:20]:
        if not isinstance(field, dict):
            continue
        field_items.append(
            {
                "name": name,
                "type": field.get("type", ""),
                "semantic": field.get("semantic", ""),
                "filterable": field.get("filterable", False),
                "sortable": field.get("sortable", False),
                "sensitive": field.get("sensitive", False),
            }
        )
    return {
        "name": detail.get("name", ""),
        "display_name": detail.get("display_name", ""),
        "database": detail.get("database", ""),
        "primary_table": detail.get("primary_table", ""),
        "source_table": detail.get("source_table", []),
        "constraint": detail.get("constraint", {}),
        "fields": field_items,
    }


async def _diagnose_request(args: dict[str, Any]) -> dict[str, Any]:
    request_id = str(args["request_id"])
    back_hours = int(args.get("back_hours", 0))
    trace = await _probe(
        "GET",
        f"/api/logs/trace/{quote(request_id, safe='')}",
        params=_clean_params(
            {
                "back_hours": back_hours,
                "hint_time": args.get("hint_time"),
                "include_full": args.get("include_full", False),
            }
        ),
    )
    if not isinstance(trace, dict) or trace.get("error"):
        return {
            "request_id": request_id,
            "trace": trace,
            "atlas_queries": [],
            "lens_candidates": [],
            "next_actions": ["check_probe_trace_error", "search_logs_by_request_id_keyword"],
        }

    terms = _diagnosis_terms(trace)
    atlas_queries: list[dict[str, Any]] = []
    lens_terms = list(terms)
    for term in terms[:6]:
        meta = await _atlas_search_metadata(term)
        matched_service = _compact_list(meta.get("matched_service"), 8)
        matched_table = _compact_list(meta.get("matched_table"), 8)
        matched_column = _compact_list(meta.get("matched_column"), 12)
        for table in matched_table:
            if isinstance(table, dict):
                _append_diagnosis_term(lens_terms, table.get("database"))
                _append_diagnosis_term(lens_terms, table.get("name"))
        for column in matched_column:
            if isinstance(column, dict):
                _append_diagnosis_term(lens_terms, column.get("database"))
                _append_diagnosis_term(lens_terms, column.get("table"))
                _append_diagnosis_term(lens_terms, column.get("column"))
        for service in matched_service:
            if isinstance(service, dict):
                databases = service.get("database_list") or service.get("databases") or []
                if isinstance(databases, str):
                    databases = [databases]
                for database in databases:
                    _append_diagnosis_term(lens_terms, database)
        atlas_queries.append(
            {
                "query": term,
                "matched_service": matched_service,
                "matched_table": matched_table,
                "matched_column": matched_column,
                "error": meta.get("error") or meta.get("service_search_error"),
            }
        )

    lens_candidates: list[dict[str, Any]] = []
    max_entities = int(args.get("max_entities", 3))
    entities_result = await _lens("GET", "/api/entities")
    entities = entities_result.get("entity", []) if isinstance(entities_result, dict) else []
    ranked = sorted(
        (
            (_entity_score(entity, lens_terms), entity)
            for entity in entities
            if isinstance(entity, dict) and _entity_score(entity, lens_terms) > 0
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    for score, entity in ranked[:max_entities]:
        name = str(entity.get("name", ""))
        if not name:
            continue
        detail = await _lens("GET", f"/api/entities/{quote(name, safe='')}")
        candidate: dict[str, Any] = {
            "score": score,
            "summary": entity,
            "detail": _summarize_entity_detail(detail),
        }
        if args.get("include_lens_counts", True):
            candidate["count"] = await _lens(
                "POST",
                "/api/entities/query",
                json_body={"entity": name, "aggregate": "count", "limit": 1},
            )
        lens_candidates.append(candidate)

    return {
        "request_id": request_id,
        "terms": terms,
        "lens_terms": lens_terms[:16],
        "trace": _summarize_trace(trace),
        "atlas_queries": atlas_queries,
        "lens_candidates": lens_candidates,
        "next_actions": [
            "read_suspect_service_context",
            "verify_atlas_metadata_matches",
            "count_or_sample_high_score_lens_entities",
            "ask_human_to_confirm_business_object_if_no_lens_candidate",
        ],
    }


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
                    "include_full": args.get("include_full"),
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
                    "exclude_noise": args.get("exclude_noise"),
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

    if name == "probe_search_ops_logs":
        return await _probe(
            "POST",
            "/api/logs/ops/search",
            json_body={
                "service": args["service"],
                "keyword": args["keyword"],
                "hosts": args["hosts"],
                "hours_back": args.get("hours_back", 1),
                "limit": args.get("limit", 50),
            },
        )

    if name == "meridian_diagnose_request":
        return await _diagnose_request(args)

    if name == "atlas_list_services":
        return await _atlas("GET", "/api/services")

    if name == "atlas_search_meta":
        return await _atlas_search_metadata(str(args["query"]))

    if name == "atlas_get_table":
        database = str(args["database"])
        table = str(args["table"])
        return await _atlas(
            "GET",
            f"/api/schemas/{quote(database, safe='')}/tables/{quote(table, safe='')}",
        )

    if name == "lens_list_entities":
        return await _lens("GET", "/api/entities")

    if name == "lens_describe_entity":
        entity = str(args["entity"])
        return await _lens("GET", f"/api/entities/{quote(entity, safe='')}")

    if name == "lens_query":
        return await _lens(
            "POST",
            "/api/entities/query",
            json_body=args,
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


@mcp.tool(name="meridian.diagnose_request")
async def meridian_diagnose_request(
    request_id: str,
    back_hours: int = 0,
    hint_time: str | None = None,
    include_full: bool = False,
    include_lens_counts: bool = True,
    max_entities: int = 3,
) -> str:
    """按 request_id 生成结构化诊断证据包：Probe 链路、Atlas 元数据、Lens 候选实体。"""
    data = await _diagnose_request(
        {
            "request_id": request_id,
            "back_hours": back_hours,
            "hint_time": hint_time,
            "include_full": include_full,
            "include_lens_counts": include_lens_counts,
            "max_entities": max_entities,
        }
    )
    return _json(data)


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
    exclude_noise: bool = False,
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
                "exclude_noise": exclude_noise,
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


@mcp.tool(name="probe.search_ops_logs")
async def probe_search_ops_logs(
    service: str,
    keyword: str,
    hosts: list[str],
    hours_back: int = 1,
    limit: int = 50,
) -> str:
    """通过 Probe ops 聚合接口跨业务主机搜索日志。默认禁用，启用后仅允许白名单 host。"""
    data = await _probe(
        "POST",
        "/api/logs/ops/search",
        json_body={
            "service": service,
            "keyword": keyword,
            "hosts": hosts,
            "hours_back": hours_back,
            "limit": limit,
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


@mcp.tool(name="devops.list_chat_sessions")
async def devops_list_chat_sessions(limit: int = 20) -> str:
    """列出最近 Agent Chat 会话摘要，用于回看卡住或重复响应的对话现场。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    sessions = await chat_session_store.list_recent(limit)
    return _json(
        {
            "count": len(sessions),
            "sessions": [session.model_dump(mode="json") for session in sessions],
            "next_actions": ["search_chat_messages", "get_chat_session"],
        }
    )


@mcp.tool(name="devops.search_chat_messages")
async def devops_search_chat_messages(keyword: str, limit: int = 20) -> str:
    """按关键词搜索 Agent Chat 会话消息和工具调用记录。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    query = keyword.strip()
    if not query:
        return _json({"error": "invalid_keyword", "detail": "keyword is required"})
    matches = await chat_session_store.search_messages(query, limit)
    return _json(
        {
            "query": query,
            "count": len(matches),
            "matches": [
                {
                    "session_id": session.id,
                    "session_title": session.title,
                    "message": message.model_dump(mode="json"),
                }
                for session, message in matches
            ],
            "next_actions": ["get_chat_session"],
        }
    )


@mcp.tool(name="devops.get_chat_session")
async def devops_get_chat_session(session_id: str) -> str:
    """按 session_id 读取完整 Agent Chat 会话，包括工具调用参数、结果、错误和耗时。"""
    if not devops.is_enabled():
        return _json(_devops_disabled())
    session = await chat_session_store.get(session_id)
    if not session:
        return _json({"error": "chat_session_not_found", "session_id": session_id})
    return _json(session.model_dump(mode="json"))


_dynamic_tools_registered = _gateway.register_dynamic_tools(mcp)


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
        return _registry_payload()

    @app.get("/api/registry/status")
    async def registry_status():
        return {
            "tool_exposure": TOOL_EXPOSURE_POLICY,
            "dynamic_tools_registered": list(_dynamic_tools_registered),
            "manifest_tools": sorted(_gateway.manifests.keys()),
            "audit_records": len(_gateway.audit_records),
            "reload": {
                "enabled": os.getenv("NEXUS_REGISTRY_RELOAD_ENABLED", "false").lower() == "true",
                "strategy": "mcp_list_changed_planned_restart_fallback",
                "note": (
                    "MCP supports notifications/tools/list_changed so clients can re-run tools/list. "
                    "Nexus does not emit that notification yet; existing tool schema/adapter changes "
                    "currently use restart as the production fallback."
                ),
            },
        }

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

    @app.get("/api/devops/chat/sessions")
    async def devops_chat_sessions_api(limit: int = 20):
        if not devops.is_enabled():
            return _devops_disabled()
        sessions = await chat_session_store.list_recent(limit)
        return {
            "count": len(sessions),
            "sessions": [session.model_dump(mode="json") for session in sessions],
        }

    @app.get("/api/devops/chat/search")
    async def devops_chat_search_api(keyword: str, limit: int = 20):
        if not devops.is_enabled():
            return _devops_disabled()
        query = keyword.strip()
        if not query:
            return {"error": "invalid_keyword", "detail": "keyword is required"}
        matches = await chat_session_store.search_messages(query, limit)
        return {
            "query": query,
            "count": len(matches),
            "matches": [
                {
                    "session_id": session.id,
                    "session_title": session.title,
                    "message": message.model_dump(mode="json"),
                }
                for session, message in matches
            ],
        }

    @app.get("/api/devops/chat/sessions/{session_id}")
    async def devops_chat_session_api(session_id: str):
        if not devops.is_enabled():
            return _devops_disabled()
        session = await chat_session_store.get(session_id)
        if not session:
            return {"error": "chat_session_not_found", "session_id": session_id}
        return session.model_dump(mode="json")

    @app.post("/api/diagnosis/request")
    async def diagnosis_request_api(body: dict):
        try:
            args = validate_tool_args("meridian_diagnose_request", body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        return await _diagnose_request(args)

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
