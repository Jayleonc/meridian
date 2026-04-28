"""Read-only DevOps helpers exposed through Nexus during development."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SERVICE_NAMES = ("nexus", "atlas", "probe", "lens", "trace")
MAX_TAIL_LINES = 500
MAX_TAIL_BYTES = 256 * 1024


def is_enabled() -> bool:
    return os.getenv("MERIDIAN_DEVOPS_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def repo_root() -> Path:
    configured = os.getenv("MERIDIAN_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def log_dir() -> Path:
    configured = os.getenv("MERIDIAN_SERVICE_LOG_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / ".meridian" / "logs"


def run_dir() -> Path:
    configured = os.getenv("MERIDIAN_RUN_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / ".meridian" / "run"


def console_status(console_dist: Path) -> dict[str, Any]:
    assets_dir = console_dist / "assets"
    assets = []
    if assets_dir.exists():
        assets = [
            {
                "name": item.name,
                "size_bytes": item.stat().st_size,
                "modified_at": _format_ts(item.stat().st_mtime),
            }
            for item in sorted(assets_dir.iterdir())
            if item.is_file()
        ]

    index = console_dist / "index.html"
    return {
        "dist_dir": str(console_dist),
        "index_exists": index.exists(),
        "index_modified_at": _format_ts(index.stat().st_mtime) if index.exists() else None,
        "asset_count": len(assets),
        "assets": assets[:20],
    }


def service_log_summary() -> dict[str, Any]:
    root = log_dir()
    return {
        "log_dir": str(root),
        "services": {service: _log_file_status(service) for service in SERVICE_NAMES},
    }


def tail_service_log(service: str, lines: int = 120) -> dict[str, Any]:
    service = _validate_service(service)
    line_count = max(1, min(lines, MAX_TAIL_LINES))
    path = _log_path(service)
    status = _log_file_status(service)
    if not path.exists():
        return {
            **status,
            "service": service,
            "lines_requested": line_count,
            "lines": [],
            "note": "log file does not exist yet",
        }

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - MAX_TAIL_BYTES))
        raw = handle.read().decode("utf-8", errors="replace")

    return {
        **status,
        "service": service,
        "lines_requested": line_count,
        "truncated_to_bytes": MAX_TAIL_BYTES if status["size_bytes"] > MAX_TAIL_BYTES else None,
        "lines": raw.splitlines()[-line_count:],
    }


def runtime_status(
    *,
    downstream: dict[str, Any],
    nexus: dict[str, Any],
    console: dict[str, Any],
) -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root()),
        "nexus": {
            **nexus,
            "pid": os.getpid(),
        },
        "downstream": downstream,
        "console": console,
        "logs": service_log_summary(),
        "run_state": _run_state_summary(),
    }


def config_check() -> dict[str, Any]:
    keys = {
        "MERIDIAN_MODEL_PROVIDER": os.getenv("MERIDIAN_MODEL_PROVIDER", ""),
        "MERIDIAN_MODEL_NAME": os.getenv("MERIDIAN_MODEL_NAME", ""),
        "MERIDIAN_MODEL_BASE_URL": _present("MERIDIAN_MODEL_BASE_URL"),
        "MERIDIAN_MODEL_API_KEY": _present("MERIDIAN_MODEL_API_KEY"),
        "OPENAI_API_KEY": _present("OPENAI_API_KEY"),
        "MERIDIAN_DEVOPS_ENABLED": os.getenv("MERIDIAN_DEVOPS_ENABLED", ""),
        "MERIDIAN_SERVICE_LOG_DIR": os.getenv("MERIDIAN_SERVICE_LOG_DIR", ""),
        "MERIDIAN_RUN_DIR": os.getenv("MERIDIAN_RUN_DIR", ""),
        "CONSOLE_DIST_DIR": os.getenv("CONSOLE_DIST_DIR", ""),
    }
    warnings = []
    provider = keys["MERIDIAN_MODEL_PROVIDER"]
    if provider in {"openai", "openai-compatible"}:
        has_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("MERIDIAN_MODEL_API_KEY"))
        if not has_key:
            warnings.append("model provider is configured but no model API key is present")
    if not log_dir().exists():
        warnings.append("service log directory does not exist yet")
    return {
        "environment": keys,
        "warnings": warnings,
    }


def smoke_result(
    *,
    downstream: dict[str, Any],
    console: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "console_index": console["index_exists"],
        "console_assets": console["asset_count"] > 0,
        "log_dir": log_dir().exists(),
    }
    for service, detail in downstream.items():
        checks[f"{service}_health"] = detail.get("status") == "ok"

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "console": console,
        "downstream": downstream,
        "logs": service_log_summary(),
    }


def _present(key: str) -> bool:
    return bool(os.getenv(key))


def _validate_service(service: str) -> str:
    normalized = service.strip().lower()
    if normalized not in SERVICE_NAMES:
        raise ValueError(f"unknown service: {service}")
    return normalized


def _log_path(service: str) -> Path:
    return log_dir() / f"{service}.log"


def _log_file_status(service: str) -> dict[str, Any]:
    path = _log_path(service)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": 0,
            "modified_at": None,
        }
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": _format_ts(stat.st_mtime),
    }


def _run_state_summary() -> dict[str, Any]:
    root = run_dir()
    state: dict[str, Any] = {"run_dir": str(root), "services": {}}
    for service in SERVICE_NAMES:
        path = root / f"{service}.json"
        state["services"][service] = _read_json(path)
    return state


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"path": str(path), "error": str(exc)}


def _format_ts(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
