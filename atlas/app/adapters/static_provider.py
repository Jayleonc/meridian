"""静态服务发现 Provider

从配置文件读取服务列表。适用于：
- 本地开发（无 supervisor）
- Docker 部署（手动声明服务）
- 任何无法自动发现的场景
"""

import logging

from app.schemas.metadata import ServiceInfo

logger = logging.getLogger("atlas.static_provider")


class StaticProvider:
    """静态配置服务发现 Provider"""

    def __init__(self, services: list[dict] | None = None):
        self._services: list[ServiceInfo] = []
        if services:
            for svc in services:
                if isinstance(svc, dict):
                    self._services.append(ServiceInfo(**svc))
                elif isinstance(svc, ServiceInfo):
                    self._services.append(svc)

    @property
    def name(self) -> str:
        return "static"

    async def is_available(self) -> bool:
        return True  # 静态配置始终可用

    async def list_services(self) -> list[ServiceInfo]:
        return list(self._services)

    async def get_service(self, name: str) -> ServiceInfo | None:
        for svc in self._services:
            if svc.name == name:
                return svc
        return None

    def register(self, service: ServiceInfo) -> None:
        """运行时动态注册服务（API 调用）"""
        # 去重
        self._services = [s for s in self._services if s.name != service.name]
        self._services.append(service)
        logger.info("静态注册服务: %s", service.name)

    def unregister(self, name: str) -> bool:
        before = len(self._services)
        self._services = [s for s in self._services if s.name != name]
        return len(self._services) < before
