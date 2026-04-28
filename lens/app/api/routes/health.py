"""健康检查 & 状态查询"""

from fastapi import APIRouter

from app.adapters.mysql_adapter import get_pool as get_mysql_pool
from app.adapters.pg_adapter import get_pool as get_pg_pool

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status")
async def status():
    """Lens 当前运行状态，包括数据库连接和已加载的 entity 概要"""
    from app.services.entity_service import get_entity_cache_info

    mysql_ok = get_mysql_pool() is not None
    pg_ok = get_pg_pool() is not None

    return {
        "connections": {
            "mysql": "connected" if mysql_ok else "disconnected",
            "postgresql": "connected" if pg_ok else "disconnected (memory mode)",
        },
        "entities": get_entity_cache_info(),
    }
