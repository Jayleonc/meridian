"""Probe 日志服务发现 Provider

Atlas 的权威服务发现仍然优先来自 supervisor / 静态配置。这个 Provider 只把
Probe 当前能观测到的 supervisor 日志服务作为兜底来源，并在 source 中明确标注。
"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from app.schemas.metadata import ServiceInfo

logger = logging.getLogger("atlas.probe_log_provider")


class ProbeLogProvider:
    """从 Probe 的日志服务列表补全服务发现。"""

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "http://127.0.0.1:3002",
        timeout_seconds: int = 5,
    ):
        self._enabled = enabled
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "probe_logs"

    async def is_available(self) -> bool:
        return self._enabled and bool(self._base_url)

    async def list_services(self) -> list[ServiceInfo]:
        if not await self.is_available():
            return []

        try:
            data = await asyncio.to_thread(self._fetch_services)
        except Exception:
            logger.warning("从 Probe 获取服务列表失败: %s", self._base_url, exc_info=True)
            return []

        services = data.get("services", [])
        if not isinstance(services, list):
            return []

        source = str(data.get("source") or "probe")
        result: list[ServiceInfo] = []
        for name in services:
            if not isinstance(name, str) or not name.strip():
                continue
            result.append(
                ServiceInfo(
                    name=name.strip(),
                    status="OBSERVED",
                    source=self.name,
                    uptime=f"via Probe: {source}",
                )
            )
        return result

    async def get_service(self, name: str) -> ServiceInfo | None:
        services = await self.list_services()
        for svc in services:
            if svc.name == name:
                return svc
        return None

    def _fetch_services(self) -> dict[str, Any]:
        query = urllib.parse.urlencode({"atlas_fallback": "false"})
        url = f"{self._base_url}/api/logs/services?{query}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, dict):
            return {}
        return data
