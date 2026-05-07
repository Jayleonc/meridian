"""Nexus registry manifest loading."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "registry_manifests" / "default.json"


def load_tool_registry(path: str | os.PathLike[str] | None = None) -> dict[str, dict[str, Any]]:
    manifest_path = Path(path or os.getenv("NEXUS_REGISTRY_MANIFEST") or DEFAULT_MANIFEST_PATH)
    with manifest_path.expanduser().open(encoding="utf-8") as file:
        manifest = json.load(file)

    registry: dict[str, dict[str, Any]] = {}
    for service in manifest.get("services", []):
        name = _required_str(service, "name")
        default_base_url = _required_str(service, "default_base_url")
        env_name = service.get("base_url_env")
        base_url = (
            os.getenv(env_name, default_base_url)
            if isinstance(env_name, str) and env_name
            else default_base_url
        ).rstrip("/")
        tool_manifests = [_normalize_tool(tool) for tool in service.get("tools", [])]

        registry[name] = {
            "name": name,
            "version": _required_str(service, "version"),
            "base_url": base_url,
            "health": _required_str(service, "health"),
            "api_prefix": _required_str(service, "api_prefix"),
            "mcp": dict(service.get("mcp", {})),
            "tools": [tool["name"] for tool in tool_manifests],
            "tool_manifests": tool_manifests,
        }

    return registry


def _normalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _required_str(tool, "name"),
        "adapter": _required_str(tool, "adapter"),
        "version": tool.get("version", "v1"),
        "status": tool.get("status", "pending"),
        "description": tool.get("description", ""),
        "chat_name": tool.get("chat_name"),
        "method": tool.get("method"),
        "path": tool.get("path"),
        "risk": tool.get("risk", "read"),
        "required_scopes": list(tool.get("required_scopes") or []),
        "input_schema": dict(tool.get("input_schema") or {"type": "object", "properties": {}}),
        "exposure": dict(tool.get("exposure") or {"mcp": True, "agent": False}),
        "approval": dict(tool.get("approval") or {}),
        "timeout_seconds": tool.get("timeout_seconds", 30),
        "downstream_timeout_seconds": tool.get("downstream_timeout_seconds", tool.get("timeout_seconds", 30)),
        "max_response_bytes": tool.get("max_response_bytes", 12000),
        "sensitive_fields": list(tool.get("sensitive_fields") or []),
        "sandbox": dict(tool.get("sandbox") or {"required": False}),
    }


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"registry manifest field is required: {key}")
    return value
