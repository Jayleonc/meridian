"""PostgreSQL 适配器 — Meridian 平台数据持久化

使用 asyncpg 连接池，自动建表，提供 Repository 函数。
如果 PG 不可用，调用方应优雅降级到纯内存模式。
"""

import json
import logging
import uuid
from datetime import datetime

import asyncpg

from app.core.config import get_settings

logger = logging.getLogger("atlas.pg")

_pool: asyncpg.Pool | None = None


# ── 连接池管理 ──────────────────────────────────


async def init_pool() -> asyncpg.Pool | None:
    """初始化连接池，建表。连不上则返回 None（降级模式）。"""
    global _pool
    if _pool is not None:
        return _pool

    cfg = get_settings().meridian_db
    try:
        _pool = await asyncpg.create_pool(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            database=cfg.database,
            min_size=2,
            max_size=10,
        )
        await _ensure_tables()
        logger.info("PostgreSQL 连接池已初始化: %s:%s/%s", cfg.host, cfg.port, cfg.database)
        return _pool
    except Exception:
        logger.warning("无法连接 PostgreSQL，将以纯内存模式运行", exc_info=True)
        _pool = None
        return None


def get_pool() -> asyncpg.Pool | None:
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL 连接池已关闭")


async def _ensure_tables() -> None:
    """首次连接时自动建表（幂等）。"""
    ddl = """
    CREATE TABLE IF NOT EXISTS schema_snapshot (
        id            UUID PRIMARY KEY,
        database_name VARCHAR(128) NOT NULL,
        snapshot_data JSONB        NOT NULL,
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_snapshot_db_time
        ON schema_snapshot (database_name, created_at DESC);

    CREATE TABLE IF NOT EXISTS semantic_annotation (
        id            UUID PRIMARY KEY,
        database_name VARCHAR(128) NOT NULL,
        table_name    VARCHAR(128) NOT NULL,
        column_name   VARCHAR(128) NOT NULL DEFAULT '',
        semantic      TEXT         NOT NULL DEFAULT '',
        source        VARCHAR(16)  NOT NULL DEFAULT 'auto',
        confirmed     BOOLEAN      NOT NULL DEFAULT FALSE,
        updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
        UNIQUE (database_name, table_name, column_name)
    );

    CREATE TABLE IF NOT EXISTS schema_changelog (
        id                UUID PRIMARY KEY,
        database_name     VARCHAR(128) NOT NULL,
        diff_data         JSONB        NOT NULL,
        snapshot_before_id UUID,
        snapshot_after_id  UUID,
        status            VARCHAR(16)  NOT NULL DEFAULT 'pending',
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_changelog_db_time
        ON schema_changelog (database_name, created_at DESC);

    CREATE TABLE IF NOT EXISTS service_metadata (
        id             UUID PRIMARY KEY,
        name           VARCHAR(256) NOT NULL UNIQUE,
        status         VARCHAR(32)  NOT NULL DEFAULT 'UNKNOWN',
        deploy_path    VARCHAR(512) NOT NULL DEFAULT '',
        log_path       VARCHAR(512) NOT NULL DEFAULT '',
        config         JSONB        NOT NULL DEFAULT '{}',
        database_list  JSONB        NOT NULL DEFAULT '[]',
        last_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id            UUID PRIMARY KEY,
        operator      VARCHAR(128) NOT NULL DEFAULT '',
        tool_name     VARCHAR(128) NOT NULL DEFAULT '',
        parameter     JSONB        NOT NULL DEFAULT '{}',
        result_count  INTEGER      NOT NULL DEFAULT 0,
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_audit_time
        ON audit_log (created_at DESC);
    """
    async with _pool.acquire() as conn:
        await conn.execute(ddl)
    logger.info("数据库表结构已就绪")


# ── Schema Snapshot Repository ──────────────────


async def save_snapshot(database_name: str, snapshot_data: list[dict], created_at: datetime | None = None) -> str:
    """持久化一次 schema 快照，返回 snapshot id。"""
    pool = get_pool()
    if not pool:
        return ""
    sid = str(uuid.uuid4())
    ts = created_at or datetime.now()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO schema_snapshot (id, database_name, snapshot_data, created_at)
            VALUES ($1, $2, $3::jsonb, $4)
            """,
            uuid.UUID(sid),
            database_name,
            json.dumps(snapshot_data, ensure_ascii=False, default=str),
            ts,
        )
    return sid


async def get_latest_snapshot(database_name: str) -> dict | None:
    """获取某个库的最新快照行，返回 {id, database_name, snapshot_data, created_at}。"""
    pool = get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, database_name, snapshot_data, created_at
            FROM schema_snapshot
            WHERE database_name = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            database_name,
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "database_name": row["database_name"],
        "snapshot_data": json.loads(row["snapshot_data"]) if isinstance(row["snapshot_data"], str) else row["snapshot_data"],
        "created_at": row["created_at"],
    }


async def list_snapshots(database_name: str, limit: int = 20) -> list[dict]:
    """列出某个库最近的快照（不含 snapshot_data，只含摘要）。"""
    pool = get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, database_name, created_at
            FROM schema_snapshot
            WHERE database_name = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            database_name,
            limit,
        )
    return [
        {"id": str(r["id"]), "database_name": r["database_name"], "created_at": r["created_at"]}
        for r in rows
    ]


# ── Schema Changelog Repository ─────────────────


async def save_changelog(
    database_name: str,
    diff_data: dict,
    snapshot_before_id: str | None = None,
    snapshot_after_id: str | None = None,
    status: str = "pending",
) -> str:
    """保存 schema diff 到 changelog，返回 changelog id。"""
    pool = get_pool()
    if not pool:
        return ""
    cid = str(uuid.uuid4())
    before_uuid = uuid.UUID(snapshot_before_id) if snapshot_before_id else None
    after_uuid = uuid.UUID(snapshot_after_id) if snapshot_after_id else None
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO schema_changelog (id, database_name, diff_data, snapshot_before_id, snapshot_after_id, status, created_at)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6, now())
            """,
            uuid.UUID(cid),
            database_name,
            json.dumps(diff_data, ensure_ascii=False, default=str),
            before_uuid,
            after_uuid,
            status,
        )
    return cid


# ── Semantic Annotation Repository ──────────────


async def save_annotation(
    database_name: str,
    table_name: str,
    column_name: str,
    semantic: str,
    source: str = "auto",
    confirmed: bool = False,
) -> str:
    """UPSERT 语义标注，返回 annotation id。"""
    pool = get_pool()
    if not pool:
        return ""
    aid = str(uuid.uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO semantic_annotation (id, database_name, table_name, column_name, semantic, source, confirmed, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, now())
            ON CONFLICT (database_name, table_name, column_name) DO UPDATE SET
                semantic   = EXCLUDED.semantic,
                source     = EXCLUDED.source,
                confirmed  = EXCLUDED.confirmed,
                updated_at = now()
            RETURNING id
            """,
            uuid.UUID(aid),
            database_name,
            table_name,
            column_name,
            semantic,
            source,
            confirmed,
        )
    return str(row["id"]) if row else aid


async def get_annotations(database_name: str, table_name: str | None = None) -> list[dict]:
    """获取某个库（可选某张表）的所有语义标注。"""
    pool = get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        if table_name:
            rows = await conn.fetch(
                """
                SELECT id, database_name, table_name, column_name, semantic, source, confirmed, updated_at
                FROM semantic_annotation
                WHERE database_name = $1 AND table_name = $2
                ORDER BY table_name, column_name
                """,
                database_name,
                table_name,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, database_name, table_name, column_name, semantic, source, confirmed, updated_at
                FROM semantic_annotation
                WHERE database_name = $1
                ORDER BY table_name, column_name
                """,
                database_name,
            )
    return [
        _annotation_row_to_dict(r)
        for r in rows
    ]


async def search_annotations(
    database_name: str,
    table_name: str | None = None,
    q: str = "",
    source: str = "",
    confirmed: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """分页搜索语义标注。"""
    pool = get_pool()
    if not pool:
        return {"total": 0, "annotations": []}

    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    conditions = ["database_name = $1"]
    args: list = [database_name]
    arg_idx = 2

    if table_name:
        conditions.append(f"table_name = ${arg_idx}")
        args.append(table_name)
        arg_idx += 1

    if q:
        conditions.append(
            f"(table_name ILIKE ${arg_idx} OR column_name ILIKE ${arg_idx} OR semantic ILIKE ${arg_idx})"
        )
        args.append(f"%{q}%")
        arg_idx += 1

    if source:
        conditions.append(f"source = ${arg_idx}")
        args.append(source)
        arg_idx += 1

    if confirmed is not None:
        conditions.append(f"confirmed = ${arg_idx}")
        args.append(confirmed)
        arg_idx += 1

    where_sql = " AND ".join(conditions)
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM semantic_annotation WHERE {where_sql}",
            *args,
        )
        rows = await conn.fetch(
            f"""
            SELECT id, database_name, table_name, column_name, semantic, source, confirmed, updated_at
            FROM semantic_annotation
            WHERE {where_sql}
            ORDER BY table_name, column_name
            LIMIT ${arg_idx} OFFSET ${arg_idx + 1}
            """,
            *args,
            limit,
            offset,
        )

    return {
        "total": total or 0,
        "annotations": [_annotation_row_to_dict(r) for r in rows],
    }


async def get_annotation(database_name: str, table_name: str, column_name: str) -> dict | None:
    """获取单条标注。"""
    pool = get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, database_name, table_name, column_name, semantic, source, confirmed, updated_at
            FROM semantic_annotation
            WHERE database_name = $1 AND table_name = $2 AND column_name = $3
            """,
            database_name,
            table_name,
            column_name,
        )
    if not row:
        return None
    return {
        **_annotation_row_to_dict(row),
    }


async def list_pending_annotations(database_name: str) -> list[dict]:
    """列出所有 confirmed=False 的标注（待人工确认，含 auto/ai 来源）。"""
    pool = get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, database_name, table_name, column_name, semantic, source, confirmed, updated_at
            FROM semantic_annotation
            WHERE database_name = $1 AND confirmed = FALSE
            ORDER BY table_name, column_name
            """,
            database_name,
        )
    return [
        _annotation_row_to_dict(r)
        for r in rows
    ]


async def confirm_annotation(
    database_name: str, table_name: str, column_name: str, confirmed: bool = True
) -> bool:
    """确认或拒绝标注。confirmed=False 时删除该标注。"""
    pool = get_pool()
    if not pool:
        return False
    async with pool.acquire() as conn:
        if not confirmed:
            result = await conn.execute(
                """
                DELETE FROM semantic_annotation
                WHERE database_name = $1 AND table_name = $2 AND column_name = $3
                """,
                database_name,
                table_name,
                column_name,
            )
            return int(result.split()[-1]) > 0
        result = await conn.execute(
            """
            UPDATE semantic_annotation
            SET confirmed = TRUE, updated_at = now()
            WHERE database_name = $1 AND table_name = $2 AND column_name = $3
            """,
            database_name,
            table_name,
            column_name,
        )
        return int(result.split()[-1]) > 0


async def confirm_annotations(annotations: list[dict], confirmed: bool = True) -> dict:
    """批量确认或驳回标注。confirmed=False 时删除对应标注。"""
    pool = get_pool()
    if not pool:
        return {"success": 0, "failed": len(annotations)}

    success = 0
    failed = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for ann in annotations:
                database_name = ann.get("database") or ann.get("database_name")
                table_name = ann.get("table") or ann.get("table_name")
                column_name = ann.get("column") or ann.get("column_name")
                if not database_name or not table_name or not column_name:
                    failed += 1
                    continue
                if confirmed:
                    result = await conn.execute(
                        """
                        UPDATE semantic_annotation
                        SET confirmed = TRUE, updated_at = now()
                        WHERE database_name = $1 AND table_name = $2 AND column_name = $3
                        """,
                        database_name,
                        table_name,
                        column_name,
                    )
                else:
                    result = await conn.execute(
                        """
                        DELETE FROM semantic_annotation
                        WHERE database_name = $1 AND table_name = $2 AND column_name = $3
                        """,
                        database_name,
                        table_name,
                        column_name,
                    )
                changed = int(result.split()[-1])
                if changed:
                    success += changed
                else:
                    failed += 1
    return {"success": success, "failed": failed}


def _annotation_row_to_dict(row) -> dict:
    """统一返回字段名，同时保留旧字段兼容前端和服务层。"""
    database_name = row["database_name"]
    table_name = row["table_name"]
    column_name = row["column_name"]
    return {
        "id": str(row["id"]),
        "database_name": database_name,
        "table_name": table_name,
        "column_name": column_name,
        "database": database_name,
        "table": table_name,
        "column": column_name,
        "semantic": row["semantic"],
        "source": row["source"],
        "confirmed": row["confirmed"],
        "updated_at": row["updated_at"],
    }


async def get_annotation_stats(database_name: str) -> dict:
    """获取标注统计：总数、已确认、待确认、各来源数量。"""
    pool = get_pool()
    if not pool:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source, confirmed, COUNT(*) as cnt
            FROM semantic_annotation
            WHERE database_name = $1
            GROUP BY source, confirmed
            """,
            database_name,
        )
    stats = {"total": 0, "confirmed": 0, "pending": 0, "by_source": {}}
    for r in rows:
        count = r["cnt"]
        source = r["source"]
        stats["total"] += count
        if r["confirmed"]:
            stats["confirmed"] += count
        else:
            stats["pending"] += count
        if source not in stats["by_source"]:
            stats["by_source"][source] = {"confirmed": 0, "pending": 0}
        key = "confirmed" if r["confirmed"] else "pending"
        stats["by_source"][source][key] = count
    return stats


async def delete_annotation(database_name: str, table_name: str, column_name: str) -> bool:
    """删除单条标注，返回是否有行被删除。"""
    pool = get_pool()
    if not pool:
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM semantic_annotation
            WHERE database_name = $1 AND table_name = $2 AND column_name = $3
            """,
            database_name,
            table_name,
            column_name,
        )
    # asyncpg returns "DELETE N" — parse the count
    return int(result.split()[-1]) > 0


# ── Service Metadata Repository ─────────────────


async def save_service(
    name: str,
    status: str = "UNKNOWN",
    deploy_path: str = "",
    log_path: str = "",
    config: dict | None = None,
    database_list: list[str] | None = None,
) -> str:
    """UPSERT 服务元数据。"""
    pool = get_pool()
    if not pool:
        return ""
    sid = str(uuid.uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO service_metadata (id, name, status, deploy_path, log_path, config, database_list, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, now())
            ON CONFLICT (name) DO UPDATE SET
                status        = EXCLUDED.status,
                deploy_path   = EXCLUDED.deploy_path,
                log_path      = EXCLUDED.log_path,
                config        = EXCLUDED.config,
                database_list = EXCLUDED.database_list,
                last_seen_at  = now()
            RETURNING id
            """,
            uuid.UUID(sid),
            name,
            status,
            deploy_path,
            log_path,
            json.dumps(config or {}, ensure_ascii=False),
            json.dumps(database_list or [], ensure_ascii=False),
        )
    return str(row["id"]) if row else sid


async def get_services() -> list[dict]:
    """获取所有服务元数据。"""
    pool = get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, deploy_path, log_path, config, database_list, last_seen_at
            FROM service_metadata
            ORDER BY name
            """
        )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "status": r["status"],
            "deploy_path": r["deploy_path"],
            "log_path": r["log_path"],
            "config": json.loads(r["config"]) if isinstance(r["config"], str) else r["config"],
            "database_list": json.loads(r["database_list"]) if isinstance(r["database_list"], str) else r["database_list"],
            "last_seen_at": r["last_seen_at"],
        }
        for r in rows
    ]


# ── Audit Log Repository ────────────────────────


async def save_audit_log(
    operator: str = "",
    tool_name: str = "",
    parameter: dict | None = None,
    result_count: int = 0,
) -> str:
    """写入审计日志。"""
    pool = get_pool()
    if not pool:
        return ""
    aid = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_log (id, operator, tool_name, parameter, result_count, created_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, now())
            """,
            uuid.UUID(aid),
            operator,
            tool_name,
            json.dumps(parameter or {}, ensure_ascii=False),
            result_count,
        )
    return aid
