"""Supervisor 服务发现 Provider

实现 ServiceDiscoveryProvider 协议。
支持两种模式：XML-RPC（优先）和日志目录扫描（兜底）。
"""

import asyncio
import logging
import re
import xmlrpc.client
from pathlib import Path

from app.schemas.metadata import ServiceInfo

logger = logging.getLogger("atlas.supervisor")


class SupervisorProvider:
    """Supervisor 服务发现 Provider"""

    def __init__(
        self,
        *,
        enabled: bool = False,
        xmlrpc_url: str = "http://127.0.0.1:9001/RPC2",
        log_dir: str = "/var/log/supervisor",
    ):
        self._enabled = enabled
        self._xmlrpc_url = xmlrpc_url
        self._log_dir = log_dir

    @property
    def name(self) -> str:
        return "supervisor"

    async def is_available(self) -> bool:
        if not self._enabled:
            return False
        # 尝试 XML-RPC 或检查日志目录
        services = await self._list_xmlrpc()
        if services:
            return True
        return Path(self._log_dir).exists()

    async def list_services(self) -> list[ServiceInfo]:
        if not self._enabled:
            return []

        # 优先 XML-RPC
        services = await self._list_xmlrpc()
        if services:
            return services

        # 兜底：日志目录扫描
        return await self._list_from_log_dir()

    async def get_service(self, name: str) -> ServiceInfo | None:
        services = await self.list_services()
        for svc in services:
            if svc.name == name:
                return svc
        return None

    # ── 内部实现 ──

    async def _list_xmlrpc(self) -> list[ServiceInfo]:
        try:
            processes = await asyncio.to_thread(
                self._fetch_xmlrpc_processes, self._xmlrpc_url
            )
        except Exception:
            return []

        services = []
        for proc in processes:
            svc = ServiceInfo(
                name=proc.get("name", ""),
                status=proc.get("statename", "UNKNOWN"),
                pid=proc.get("pid", 0) or None,
                uptime=str(proc.get("description", "")),
            )
            services.append(svc)
        return services

    @staticmethod
    def _fetch_xmlrpc_processes(url: str) -> list[dict]:
        server = xmlrpc.client.ServerProxy(url)
        return server.supervisor.getAllProcessInfo()

    async def _list_from_log_dir(self) -> list[ServiceInfo]:
        log_dir = Path(self._log_dir)

        def _scan() -> list[str]:
            if not log_dir.exists():
                return []
            pattern = re.compile(r"^(.+?)-stdout---supervisor-.*\.log$")
            names: set[str] = set()
            for f in log_dir.iterdir():
                match = pattern.match(f.name)
                if match:
                    names.add(match.group(1))
            return sorted(names)

        service_names = await asyncio.to_thread(_scan)
        return [ServiceInfo(name=n) for n in service_names]


# ── 向后兼容：保留模块级函数 ──

async def list_services() -> list[ServiceInfo]:
    """向后兼容：从配置创建 Provider 并调用"""
    from app.core.config import get_settings
    cfg = get_settings().supervisor
    provider = SupervisorProvider(
        enabled=cfg.enabled,
        xmlrpc_url=cfg.xmlrpc_url,
        log_dir=cfg.log_dir,
    )
    return await provider.list_services()
