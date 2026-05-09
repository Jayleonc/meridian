"""连接池注册表

按名称管理多个 BusinessDBAdapter 实例。
Lifespan 中统一初始化和关闭。
"""

import logging

from app.adapters.protocol import BusinessDBAdapter

logger = logging.getLogger("lens.registry")

_adapters: dict[str, BusinessDBAdapter] = {}


def register(name: str, adapter: BusinessDBAdapter) -> None:
    """注册一个业务数据库适配器"""
    if name in _adapters:
        logger.warning("适配器 '%s' 已存在，将被覆盖", name)
    _adapters[name] = adapter
    logger.info("注册适配器: %s (type=%s)", name, adapter.db_type)


def get(name: str) -> BusinessDBAdapter | None:
    """按名称获取适配器"""
    return _adapters.get(name)


def get_by_type(db_type: str) -> BusinessDBAdapter | None:
    """按数据库类型获取第一个匹配的适配器（便捷方法）"""
    for adapter in _adapters.values():
        if adapter.db_type == db_type:
            return adapter
    return None


def get_default() -> BusinessDBAdapter | None:
    """获取默认适配器（第一个注册的）"""
    if _adapters:
        return next(iter(_adapters.values()))
    return None


def list_adapters() -> list[dict]:
    """列出所有已注册的适配器（用于 /status 端点）"""
    result = []
    for name, adapter in _adapters.items():
        pool = getattr(adapter, "pool", None)
        if pool is None:
            pool = getattr(adapter, "_pool", None)
        result.append({
            "name": name,
            "db_type": adapter.db_type,
            "connected": pool is not None,
        })
    return result


async def init_all() -> None:
    """初始化所有已注册适配器的连接池"""
    for name, adapter in _adapters.items():
        try:
            await adapter.init_pool()
        except Exception:
            logger.error("适配器 '%s' 初始化失败", name, exc_info=True)


async def close_all() -> None:
    """关闭所有已注册适配器的连接池"""
    for name, adapter in _adapters.items():
        try:
            await adapter.close_pool()
        except Exception:
            logger.error("适配器 '%s' 关闭失败", name, exc_info=True)
    _adapters.clear()


def clear() -> None:
    """清空注册表（测试用）"""
    _adapters.clear()
