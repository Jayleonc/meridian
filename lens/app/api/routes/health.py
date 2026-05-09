"""健康检查 & 状态查询"""

from fastapi import APIRouter

from app.adapters import registry
from app.adapters.pg_adapter import get_pool as get_pg_pool

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status")
async def status():
    """Lens 当前运行状态，包括数据库连接和已加载的 entity 概要"""
    from app.services.entity_service import get_entity_cache_info

    datasource = registry.list_adapters()
    mysql_ok = any(
        item.get("db_type") == "mysql" and item.get("connected")
        for item in datasource
    )
    pg_ok = get_pg_pool() is not None

    return {
        "connections": {
            "mysql": "connected" if mysql_ok else "disconnected",
            "postgresql": "connected" if pg_ok else "disconnected (memory mode)",
        },
        "datasource": datasource,
        "entities": get_entity_cache_info(),
    }
