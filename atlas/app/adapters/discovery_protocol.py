"""服务发现 Provider 协议

所有服务发现方式（Supervisor、Docker、Systemd、静态配置）必须实现此协议。
"""

from typing import Protocol, runtime_checkable

from app.schemas.metadata import ServiceInfo


@runtime_checkable
class ServiceDiscoveryProvider(Protocol):
    """服务发现 Provider 协议"""

    @property
    def name(self) -> str:
        """Provider 名称（用于日志和配置引用）"""
        ...

    async def is_available(self) -> bool:
        """Provider 是否可用"""
        ...

    async def list_services(self) -> list[ServiceInfo]:
        """列出所有服务"""
        ...

    async def get_service(self, name: str) -> ServiceInfo | None:
        """获取单个服务详情"""
        ...
