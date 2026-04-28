"""Entity 服务 — 管理业务对象定义

内存缓存 + PG 持久化，启动时从 PG 加载，PG 不可用时纯内存模式。
"""

import logging

from app.adapters import pg_adapter
from app.schemas.query import EntityConstraint, EntityDefinition, EntityField

logger = logging.getLogger("lens.entity")

# ── 内存缓存 ──────────────────────────────────
_entity_cache: dict[str, EntityDefinition] = {}


async def load_from_pg() -> int:
    """从 PG 加载所有 entity definition 到缓存，返回加载数量。"""
    rows = await pg_adapter.list_entities(enabled_only=False)
    count = 0
    for row in rows:
        entity = _row_to_definition(row)
        _entity_cache[entity.name] = entity
        count += 1
    if count:
        logger.info("从 PG 加载了 %d 个 entity definition", count)
    return count


def _row_to_definition(row: dict) -> EntityDefinition:
    """将 PG 返回的 dict 转换为 EntityDefinition。"""
    fields = {}
    raw_fields = row.get("fields", {})
    for fname, fdata in raw_fields.items():
        if isinstance(fdata, dict):
            fields[fname] = EntityField(**fdata)
        else:
            fields[fname] = EntityField(name=fname)

    raw_constraint = row.get("query_constraint", {})
    constraint = EntityConstraint(**raw_constraint) if raw_constraint else EntityConstraint()

    return EntityDefinition(
        id=row.get("id", ""),
        name=row["name"],
        display_name=row.get("display_name", ""),
        database=row.get("database_name", ""),
        db_type=row.get("db_type", "mysql"),
        datasource=row.get("datasource", ""),
        source_table=row.get("source_table", []),
        primary_table=row.get("primary_table", ""),
        join_clause=row.get("join_clause", ""),
        fields=fields,
        constraint=constraint,
        enabled=row.get("enabled", True),
    )


# ── 读操作 ──────────────────────────────────


async def get_entity_definition(name: str) -> EntityDefinition | None:
    """获取 entity definition，先查缓存，再查 PG。"""
    if name in _entity_cache:
        return _entity_cache[name]

    # 尝试从 PG 加载
    row = await pg_adapter.get_entity(name)
    if row:
        entity = _row_to_definition(row)
        _entity_cache[entity.name] = entity
        return entity

    return None


async def list_entity_definitions(enabled_only: bool = True) -> list[EntityDefinition]:
    """列出所有 entity definition。"""
    if _entity_cache:
        entities = list(_entity_cache.values())
        if enabled_only:
            entities = [e for e in entities if e.enabled]
        return sorted(entities, key=lambda e: e.name)

    # 缓存为空，尝试从 PG 加载
    await load_from_pg()
    entities = list(_entity_cache.values())
    if enabled_only:
        entities = [e for e in entities if e.enabled]
    return sorted(entities, key=lambda e: e.name)


# ── 写操作 ──────────────────────────────────


async def register_entity(
    name: str,
    display_name: str = "",
    database: str = "",
    db_type: str = "mysql",
    datasource: str = "",
    source_table: list[str] | None = None,
    primary_table: str = "",
    join_clause: str = "",
    fields: dict[str, dict] | None = None,
    constraint: dict | None = None,
    enabled: bool = True,
) -> EntityDefinition:
    """注册或更新一个 entity definition。写入 PG + 更新缓存。"""
    # 构建 fields dict for PG
    fields_for_pg = {}
    parsed_fields = {}
    if fields:
        for fname, fdata in fields.items():
            if isinstance(fdata, dict):
                ef = EntityField(**{**fdata, "name": fname})
            else:
                ef = EntityField(name=fname)
            parsed_fields[fname] = ef
            fields_for_pg[fname] = ef.model_dump()

    # 写 PG
    eid = await pg_adapter.save_entity(
        name=name,
        display_name=display_name,
        database_name=database,
        db_type=db_type,
        datasource=datasource,
        source_table=source_table,
        primary_table=primary_table,
        join_clause=join_clause,
        fields=fields_for_pg,
        query_constraint=constraint,
        enabled=enabled,
    )

    entity = EntityDefinition(
        id=eid,
        name=name,
        display_name=display_name,
        database=database,
        db_type=db_type,
        datasource=datasource,
        source_table=source_table or [],
        primary_table=primary_table,
        join_clause=join_clause,
        fields=parsed_fields,
        constraint=EntityConstraint(**constraint) if constraint else EntityConstraint(),
        enabled=enabled,
    )

    # 更新缓存
    _entity_cache[name] = entity
    logger.info("Entity '%s' 已注册/更新", name)
    return entity


async def delete_entity_definition(name: str) -> bool:
    """删除 entity definition。"""
    deleted = await pg_adapter.delete_entity(name)
    _entity_cache.pop(name, None)
    return deleted


# ── 状态查询 ──────────────────────────────────


def get_entity_cache_info() -> dict:
    """返回缓存状态（用于 /status 端点）。"""
    return {
        "cached_count": len(_entity_cache),
        "entities": [
            {"name": e.name, "display_name": e.display_name, "enabled": e.enabled}
            for e in _entity_cache.values()
        ],
    }
