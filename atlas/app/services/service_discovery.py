"""服务发现 — 通过 Provider 注册表采集和管理业务服务列表

支持多个 Provider（Supervisor、Static 等），按优先级尝试。
"""

import logging

from app.adapters.discovery_protocol import ServiceDiscoveryProvider
from app.schemas.metadata import ServiceInfo

logger = logging.getLogger("atlas.discovery")

# Provider 注册表（按优先级排序）
_providers: list[ServiceDiscoveryProvider] = []

# 内存缓存
_service_cache: list[ServiceInfo] = []


def register_provider(provider: ServiceDiscoveryProvider) -> None:
    """注册一个服务发现 Provider"""
    _providers.append(provider)
    logger.info("注册服务发现 Provider: %s", provider.name)


def list_providers() -> list[str]:
    """列出所有已注册的 Provider 名称"""
    return [p.name for p in _providers]


async def refresh_services() -> list[ServiceInfo]:
    """刷新服务列表 — 按优先级遍历 Provider，合并结果"""
    global _service_cache
    all_services: dict[str, ServiceInfo] = {}

    for provider in _providers:
        try:
            if not await provider.is_available():
                logger.debug("Provider '%s' 不可用，跳过", provider.name)
                continue

            services = await provider.list_services()
            for svc in services:
                # 后注册的 Provider 不覆盖先注册的（优先级高的先注册）
                if svc.name not in all_services:
                    all_services[svc.name] = svc

            if services:
                logger.info("Provider '%s' 返回 %d 个服务", provider.name, len(services))
        except Exception:
            logger.warning("Provider '%s' 执行失败", provider.name, exc_info=True)

    _service_cache = sorted(all_services.values(), key=lambda s: s.name)
    return _service_cache


async def get_services() -> list[ServiceInfo]:
    """获取服务列表（优先返回缓存）"""
    if not _service_cache:
        return await refresh_services()
    return _service_cache


async def get_service_detail(name: str) -> ServiceInfo | None:
    """获取指定服务的详情"""
    services = await get_services()
    for svc in services:
        if svc.name == name:
            return svc
    return None


def upsert_services(services: list[ServiceInfo]) -> None:
    """将运行时服务声明写入缓存。

    主要用于本地 demo 自举，不改变任何 Provider 配置。
    """
    global _service_cache
    merged = {svc.name: svc for svc in _service_cache}
    for service in services:
        merged[service.name] = service
    _service_cache = sorted(merged.values(), key=lambda s: s.name)


def clear() -> None:
    """清空 Provider 和缓存（测试用）"""
    _providers.clear()
    _service_cache.clear()
