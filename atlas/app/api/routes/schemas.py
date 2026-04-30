"""Schema 管理 REST API

供 Console 前端浏览数据库结构、对比变更、搜索元数据。
"""

from fastapi import APIRouter, Query

from app.services.schema_service import (
    collect_all,
    collect_schema,
    diff_schema,
    get_latest_snapshot,
    get_table_info,
    search_metadata,
)
from app.services.demo_data import seed_demo

router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.get("")
async def list_databases():
    """列出所有已采集的数据库及其表数量"""
    from app.services.schema_service import _snapshots

    result = []
    for db, snapshots in _snapshots.items():
        if snapshots:
            latest = snapshots[-1]
            result.append({
                "database": db,
                "table_count": len(latest.table),
                "snapshot_count": len(snapshots),
                "last_collected": str(latest.created_at) if latest.created_at else None,
            })
    return {"databases": result}


@router.get("/{database}")
async def get_database_schema(database: str):
    """获取指定数据库的完整 schema — 包含所有表和字段"""
    snapshot = await get_latest_snapshot(database)
    if not snapshot:
        return {"error": f"数据库 '{database}' 无快照数据，请先触发采集", "database": database}
    return snapshot.model_dump()


@router.get("/{database}/tables")
async def list_tables(database: str):
    """列出指定数据库的所有表（精简信息）"""
    snapshot = await get_latest_snapshot(database)
    if not snapshot:
        return {"error": f"数据库 '{database}' 无快照数据", "tables": []}
    return {
        "database": database,
        "count": len(snapshot.table),
        "tables": [
            {
                "name": t.name,
                "comment": t.comment,
                "column_count": len(t.column),
                "row_count_approx": t.row_count_approx,
                "engine": t.engine,
            }
            for t in snapshot.table
        ],
    }


@router.get("/{database}/tables/{table}")
async def get_table_detail(database: str, table: str):
    """获取单张表的详细信息（含字段列表）"""
    info = await get_table_info(database, table)
    if not info:
        return {"error": f"表 '{database}.{table}' 不存在"}
    return info.model_dump()


@router.get("/{database}/diff")
async def get_schema_diff(database: str):
    """对比最新快照与上一次快照的差异"""
    diff = await diff_schema(database)
    if not diff:
        return {"message": "无差异或仅有一个快照", "database": database}
    return diff.model_dump()


@router.post("/collect")
async def trigger_collect(database: str = Query("", description="留空则采集全部")):
    """手动触发 schema 采集"""
    if database:
        snapshot = await collect_schema(database)
        return {
            "collected": 1,
            "database": snapshot.database,
            "table_count": len(snapshot.table),
        }
    else:
        snapshots = await collect_all()
        return {
            "collected": len(snapshots),
            "databases": [
                {"database": s.database, "table_count": len(s.table)}
                for s in snapshots
            ],
        }


@router.post("/demo")
async def bootstrap_demo_schema():
    """显式加载本地 demo schema 与服务，用于无业务库时验证 Atlas/Lens 页面。"""
    return await seed_demo()


@router.get("/search/meta")
async def search_meta(q: str = Query(..., min_length=1, description="搜索关键词")):
    """全文搜索元数据 — 按表名、字段名、注释、语义标签匹配"""
    result = await search_metadata(q)
    return result
