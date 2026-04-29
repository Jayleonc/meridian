"""Schema 采集与 Diff 服务

内存缓存 + PostgreSQL 持久化。PG 不可用时自动降级到纯内存模式。
"""

import logging
from datetime import datetime

from app.adapters import pg_adapter
from app.adapters.mysql_adapter import fetch_full_schema
from app.core.config import get_settings
from app.schemas.metadata import (
    ColumnDiff,
    ColumnInfo,
    SchemaDiff,
    SchemaSnapshot,
    TableDiff,
    TableInfo,
)
from app.services import annotation_service
from app.utils.semantic import infer_semantic

logger = logging.getLogger(__name__)

# 内存中的快照缓存（PG 可用时同时持久化）
_snapshots: dict[str, list[SchemaSnapshot]] = {}  # database -> [snapshots]


async def _ensure_cache(database: str) -> None:
    """缓存为空时，尝试从 PG 加载最新快照。"""
    if database in _snapshots and _snapshots[database]:
        return

    try:
        row = await pg_adapter.get_latest_snapshot(database)
    except Exception:
        logger.debug("从 PG 加载快照失败，跳过", exc_info=True)
        return

    if not row:
        return

    tables = [TableInfo(**t) for t in row["snapshot_data"]]
    snapshot = SchemaSnapshot(
        id=row["id"],
        database=database,
        table=tables,
        created_at=row["created_at"],
    )
    _snapshots[database] = [snapshot]
    logger.info("从 PG 恢复快照缓存: %s (%d 张表)", database, len(tables))


async def collect_schema(database: str) -> SchemaSnapshot:
    """采集一个数据库的完整 schema，生成快照

    即使采集失败也返回快照（空表列表），不会抛出异常。
    """
    try:
        tables = await fetch_full_schema(database)
    except Exception as exc:
        logger.error("Failed to collect schema for database '%s': %s", database, exc)
        tables = []

    # 加载 PG 中已有的人工标注，用于合并
    auto_annotations: list[tuple[str, str, str, str]] = []  # (db, table, column, semantic)

    for table in tables:
        # 获取该表的人工标注
        table_manual: dict[str, dict] = {}
        try:
            table_manual = await annotation_service.get_merged_semantics(database, table.name)
        except Exception:
            pass

        for col in table.column:
            # 如果 PG 里有 manual/rule 标注，优先使用
            if col.name in table_manual:
                ann = table_manual[col.name]
                col.semantic = ann["semantic"]
                col.semantic_source = ann["source"]
                continue

            # 否则走自动推断
            if not col.semantic:
                col.semantic = infer_semantic(col.name, col.type, col.comment)
                col.semantic_source = "auto" if col.semantic else ""

            # 记录自动推断结果，稍后批量写入 PG
            if col.semantic and col.semantic_source == "auto":
                auto_annotations.append((database, table.name, col.name, col.semantic))

    now = datetime.now()
    snapshot = SchemaSnapshot(
        database=database,
        table=tables,
        created_at=now,
    )

    # 保存到内存缓存（最多保留 10 份）
    if database not in _snapshots:
        _snapshots[database] = []
    _snapshots[database].append(snapshot)
    if len(_snapshots[database]) > 10:
        _snapshots[database] = _snapshots[database][-10:]

    # 持久化到 PG
    try:
        snapshot_data = [t.model_dump() for t in tables]
        sid = await pg_adapter.save_snapshot(database, snapshot_data, created_at=now)
        if sid:
            snapshot.id = sid
            logger.info("快照已持久化: %s (id=%s, %d 张表)", database, sid, len(tables))

            # 保存自动推断的标注（仅写 PG 里还没有标注的字段）
            for db, tbl, col_name, semantic in auto_annotations:
                existing = await pg_adapter.get_annotation(db, tbl, col_name)
                if not existing:
                    await pg_adapter.save_annotation(
                        database_name=db,
                        table_name=tbl,
                        column_name=col_name,
                        semantic=semantic,
                        source="auto",
                        confirmed=False,
                    )
    except Exception:
        logger.warning("快照持久化失败，仅保留内存缓存", exc_info=True)

    return snapshot


async def collect_all() -> list[SchemaSnapshot]:
    """采集所有配置的业务数据库

    单个数据库失败不影响其余数据库的采集，返回部分结果。
    """
    cfg = get_settings()
    snapshots = []
    errors: list[dict] = []

    for db in cfg.business_mysql.database:
        try:
            snapshot = await collect_schema(db)
            snapshots.append(snapshot)
        except Exception as exc:
            logger.error("Unexpected error collecting schema for '%s': %s", db, exc)
            errors.append({"database": db, "error": str(exc)})

    if errors:
        logger.warning(
            "Schema collection completed with %d error(s): %s",
            len(errors),
            errors,
        )

    return snapshots


async def restore_all_latest_snapshots() -> list[SchemaSnapshot]:
    """从 PG 恢复所有已配置数据库的最新快照，不触碰业务 MySQL。"""
    cfg = get_settings()
    snapshots = []

    for db in cfg.business_mysql.database:
        await _ensure_cache(db)
        cached = _snapshots.get(db, [])
        if cached:
            snapshots.append(cached[-1])

    return snapshots


async def get_latest_snapshot(database: str) -> SchemaSnapshot | None:
    """获取某个数据库的最新快照（先查缓存，缓存空则查 PG）"""
    await _ensure_cache(database)
    snapshots = _snapshots.get(database, [])
    return snapshots[-1] if snapshots else None


async def diff_schema(database: str) -> SchemaDiff | None:
    """对比最新两次快照的差异"""
    await _ensure_cache(database)
    snapshots = _snapshots.get(database, [])
    if len(snapshots) < 2:
        return None

    old = snapshots[-2]
    new = snapshots[-1]

    old_tables = {t.name: t for t in old.table}
    new_tables = {t.name: t for t in new.table}

    added = [name for name in new_tables if name not in old_tables]
    removed = [name for name in old_tables if name not in new_tables]

    modified = []
    for name in set(old_tables) & set(new_tables):
        table_diff = _diff_table(old_tables[name], new_tables[name])
        if table_diff:
            modified.append(table_diff)

    diff = SchemaDiff(
        database=database,
        added_table=added,
        removed_table=removed,
        modified_table=modified,
        snapshot_time=new.created_at,
        previous_time=old.created_at,
    )

    # 持久化 diff 到 changelog
    try:
        if added or removed or modified:
            await pg_adapter.save_changelog(
                database_name=database,
                diff_data=diff.model_dump(mode="json"),
                snapshot_before_id=old.id or None,
                snapshot_after_id=new.id or None,
                status="pending",
            )
    except Exception:
        logger.warning("保存 schema changelog 失败", exc_info=True)

    return diff


def _diff_column(old: ColumnInfo, new: ColumnInfo) -> ColumnDiff | None:
    """对比两个字段的所有属性差异，返回 ColumnDiff 或 None（无变化）"""
    change_detail: list[str] = []

    if old.type != new.type:
        change_detail.append("type")
    if old.comment != new.comment:
        change_detail.append("comment")
    if old.nullable != new.nullable:
        change_detail.append("nullable")
    if old.is_primary_key != new.is_primary_key:
        change_detail.append("is_primary_key")
    if old.is_index != new.is_index:
        change_detail.append("is_index")

    if not change_detail:
        return None

    return ColumnDiff(
        name=old.name,
        old_type=old.type,
        new_type=new.type,
        old_comment=old.comment if "comment" in change_detail else None,
        new_comment=new.comment if "comment" in change_detail else None,
        old_nullable=old.nullable if "nullable" in change_detail else None,
        new_nullable=new.nullable if "nullable" in change_detail else None,
        change="modified",
        change_detail=change_detail,
    )


def _diff_table(old: TableInfo, new: TableInfo) -> TableDiff | None:
    """对比两个表的字段差异（类型、注释、可空、索引）"""
    old_cols = {c.name: c for c in old.column}
    new_cols = {c.name: c for c in new.column}

    added = [
        ColumnDiff(name=n, new_type=new_cols[n].type, change="added")
        for n in new_cols
        if n not in old_cols
    ]
    removed = [
        ColumnDiff(name=n, old_type=old_cols[n].type, change="removed")
        for n in old_cols
        if n not in new_cols
    ]

    modified = []
    for n in set(old_cols) & set(new_cols):
        col_diff = _diff_column(old_cols[n], new_cols[n])
        if col_diff:
            modified.append(col_diff)

    if not added and not removed and not modified:
        return None

    return TableDiff(
        table=old.name,
        added_column=added,
        removed_column=removed,
        modified_column=modified,
    )


async def get_table_info(database: str, table_name: str) -> TableInfo | None:
    """从最新快照中获取指定表信息"""
    snapshot = await get_latest_snapshot(database)
    if not snapshot:
        return None
    for t in snapshot.table:
        if t.name == table_name:
            return t
    return None


async def search_metadata(query: str) -> dict:
    """全文搜索元数据（表名、字段名、语义描述）"""
    query_lower = query.lower()
    matched_tables = []
    matched_columns = []

    for db, snapshots in _snapshots.items():
        if not snapshots:
            continue
        latest = snapshots[-1]
        for table in latest.table:
            # 匹配表名或表注释
            if query_lower in table.name.lower() or query_lower in table.comment.lower():
                matched_tables.append(table.model_dump())

            # 匹配字段名、注释或语义
            for col in table.column:
                if (
                    query_lower in col.name.lower()
                    or query_lower in col.comment.lower()
                    or query_lower in col.semantic.lower()
                ):
                    matched_columns.append(
                        {
                            "database": db,
                            "table": table.name,
                            "column": col.name,
                            "type": col.type,
                            "comment": col.comment,
                            "semantic": col.semantic,
                        }
                    )

    return {
        "query": query,
        "matched_table": matched_tables[:20],
        "matched_column": matched_columns[:50],
    }
