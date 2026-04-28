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
    """Atlas 当前运行状态，包括数据库连接和已采集的 schema 概要"""
    from app.services.schema_service import _snapshots

    mysql_ok = get_mysql_pool() is not None
    pg_ok = get_pg_pool() is not None

    databases = {}
    for db, snapshots in _snapshots.items():
        if snapshots:
            latest = snapshots[-1]
            databases[db] = {
                "table_count": len(latest.table),
                "snapshot_time": str(latest.created_at),
                "snapshot_count": len(snapshots),
            }

    return {
        "connections": {
            "mysql": "connected" if mysql_ok else "disconnected",
            "postgresql": "connected" if pg_ok else "disconnected (memory mode)",
        },
        "databases": databases,
        "total_databases": len(databases),
    }
