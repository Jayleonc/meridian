"""Controlled Nexus tool gateway pipeline."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_CALLER_SCOPES = {
    scope.strip()
    for scope in os.getenv(
        "NEXUS_DEFAULT_SCOPES",
        "read:schema,read:logs,read:business,read:health",
    ).split(",")
    if scope.strip()
}
DEFAULT_AUDIT_LOG_PATH = (
    Path(os.getenv("NEXUS_AUDIT_LOG_PATH", ""))
    if os.getenv("NEXUS_AUDIT_LOG_PATH")
    else Path(__file__).resolve().parents[2] / ".meridian" / "logs" / "nexus-tool-audit.jsonl"
)
SECRET_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key)=([^&\\s]+)"),
    re.compile(r"\\b1[3-9]\\d{9}\\b"),
]


class ToolGateway:
    def __init__(
        self,
        registry: dict[str, dict[str, Any]],
        *,
        audit_log_path: Path | None = DEFAULT_AUDIT_LOG_PATH,
    ) -> None:
        self.registry = registry
        self.audit_log_path = audit_log_path
        self.audit_records: list[dict[str, Any]] = []
        self.manifests = {
            tool["name"]: {**tool, "service": service["name"], "base_url": service["base_url"]}
            for service in registry.values()
            for tool in service.get("tool_manifests", [])
        }

    def dynamic_tool_names(self) -> list[str]:
        return [
            name
            for name, manifest in self.manifests.items()
            if _is_approved_mcp_tool(manifest)
        ]

    def register_dynamic_tools(self, mcp: FastMCP) -> list[str]:
        registered: list[str] = []
        for name in self.dynamic_tool_names():
            if mcp._tool_manager.get_tool(name):
                continue
            manifest = self.manifests[name]
            mcp.add_tool(
                _make_dynamic_handler(self, manifest),
                name=name,
                description=str(manifest.get("description") or f"Nexus managed tool {name}"),
                structured_output=False,
            )
            registered.append(name)
        return registered

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        caller_scopes: set[str] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        manifest = self.manifests.get(tool_name)
        trace_id = trace_id or str(uuid.uuid4())
        started = time.perf_counter()
        if not manifest:
            return self._record_result(
                trace_id,
                tool_name,
                args,
                started,
                {"error": "tool_not_registered", "tool": tool_name},
            )

        effective_scopes = DEFAULT_CALLER_SCOPES if caller_scopes is None else caller_scopes
        auth_error = _authorize(manifest, effective_scopes)
        if auth_error:
            return self._record_result(trace_id, tool_name, args, started, auth_error)

        if manifest.get("status") != "approved":
            result = {
                "error": "tool_not_approved",
                "tool": tool_name,
                "status": manifest.get("status", "pending"),
            }
            return self._record_result(trace_id, tool_name, args, started, result)

        timeout_seconds = float(manifest.get("timeout_seconds") or 30)
        try:
            result = await asyncio.wait_for(
                self._execute_adapter(manifest, args),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            result = {
                "error": "tool_timeout",
                "tool": tool_name,
                "timeout_seconds": timeout_seconds,
            }
        except Exception as exc:  # pragma: no cover - defensive isolation
            result = {
                "error": "tool_execution_failed",
                "tool": tool_name,
                "detail": str(exc)[:500],
            }

        redacted = _redact_value(result, set(manifest.get("sensitive_fields") or []))
        bounded = _truncate_value(redacted, int(manifest.get("max_response_bytes") or 12000))
        return self._record_result(trace_id, tool_name, args, started, bounded)

    async def _execute_adapter(self, manifest: dict[str, Any], args: dict[str, Any]) -> Any:
        adapter = manifest.get("adapter")
        if adapter != "http":
            return {
                "error": "unsupported_adapter",
                "adapter": adapter,
                "tool": manifest["name"],
            }

        method = str(manifest.get("method") or "GET").upper()
        path = _format_path(str(manifest.get("path") or ""), args)
        url = f"{manifest['base_url']}{path}"
        path_keys = set(re.findall(r"{([^{}]+)}", str(manifest.get("path") or "")))
        remaining_args = {key: value for key, value in args.items() if key not in path_keys}
        timeout_seconds = float(
            manifest.get("downstream_timeout_seconds") or manifest.get("timeout_seconds") or 30
        )

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                if method in {"GET", "DELETE"}:
                    response = await client.request(method, url, params=remaining_args)
                else:
                    response = await client.request(method, url, json=remaining_args)
                response.raise_for_status()
                if response.content:
                    return response.json()
                return {"status": "ok"}
        except httpx.HTTPStatusError as exc:
            return {
                "error": "downstream_http_error",
                "service": manifest["service"],
                "status_code": exc.response.status_code,
                "body": exc.response.text[:500],
            }
        except httpx.RequestError as exc:
            return {
                "error": "downstream_unavailable",
                "service": manifest["service"],
                "detail": str(exc)[:500],
            }

    def _record_result(
        self,
        trace_id: str,
        tool_name: str,
        args: dict[str, Any],
        started: float,
        result: dict[str, Any] | list[Any] | Any,
    ) -> dict[str, Any]:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        result_text = json.dumps(result, ensure_ascii=False, default=str)
        record = {
            "trace_id": trace_id,
            "tool": tool_name,
            "parameter": _redact_value(args, {"password", "token", "secret", "api_key"}),
            "duration_ms": elapsed_ms,
            "result_bytes": len(result_text.encode("utf-8")),
            "error": result.get("error") if isinstance(result, dict) else None,
            "created_at": time.time(),
        }
        self.audit_records.append(record)
        _append_audit_record(self.audit_log_path, record)
        if isinstance(result, dict):
            return {"trace_id": trace_id, **result}
        return {"trace_id": trace_id, "result": result}


def _make_dynamic_handler(gateway: ToolGateway, manifest: dict[str, Any]):
    async def handler(**kwargs: Any) -> str:
        result = await gateway.execute(manifest["name"], kwargs)
        return json.dumps(result, ensure_ascii=False, default=str)

    handler.__name__ = manifest["name"].replace(".", "_")
    handler.__doc__ = str(manifest.get("description") or "")
    handler.__signature__ = _signature_from_schema(manifest.get("input_schema") or {})
    return handler


def _signature_from_schema(schema: dict[str, Any]) -> inspect.Signature:
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    parameters: list[inspect.Parameter] = []
    for name, field_schema in (properties or {}).items():
        default = inspect.Parameter.empty if name in required else field_schema.get("default", None)
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_annotation_for_json_type(field_schema),
            )
        )
    return inspect.Signature(parameters=parameters, return_annotation=str)


def _annotation_for_json_type(schema: dict[str, Any]) -> Any:
    json_type = schema.get("type")
    if json_type == "integer":
        return int
    if json_type == "number":
        return float
    if json_type == "boolean":
        return bool
    if json_type == "array":
        return list[Any]
    if json_type == "object":
        return dict[str, Any]
    return str


def _is_approved_mcp_tool(manifest: dict[str, Any]) -> bool:
    exposure = manifest.get("exposure") or {}
    return manifest.get("status") == "approved" and bool(exposure.get("mcp", True))


def _authorize(manifest: dict[str, Any], caller_scopes: set[str]) -> dict[str, Any] | None:
    required = set(manifest.get("required_scopes") or [])
    if required and not required.issubset(caller_scopes):
        return {
            "error": "permission_denied",
            "tool": manifest["name"],
            "required_scopes": sorted(required),
        }
    return None


def _format_path(path: str, args: dict[str, Any]) -> str:
    for key, value in args.items():
        path = path.replace("{" + key + "}", quote(str(value), safe=""))
    return path


def _redact_value(value: Any, sensitive_fields: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if key in sensitive_fields else _redact_value(item, sensitive_fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, sensitive_fields) for item in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            text = pattern.sub(_redact_match, text)
        return text
    return value


def _redact_match(match: re.Match[str]) -> str:
    matched = match.group(0)
    if "=" in matched:
        return matched.split("=", 1)[0] + "=***REDACTED***"
    return "***REDACTED***"


def _truncate_value(value: Any, max_bytes: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) <= max_bytes:
        return value
    return {
        "truncated": True,
        "original_bytes": len(text.encode("utf-8")),
        "preview": text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore"),
    }


def _append_audit_record(path: Path | None, record: dict[str, Any]) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return
