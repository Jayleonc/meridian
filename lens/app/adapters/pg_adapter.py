"""PostgreSQL 适配器 — Lens 平台数据持久化

存储 entity_definition 和查询审计日志。
如果 PG 不可用，调用方应优雅降级到纯内存模式。
"""

import json
import logging
import uuid

import asyncpg

from app.core.config import get_settings

logger = logging.getLogger("lens.pg")

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
    CREATE TABLE IF NOT EXISTS entity_definition (
        id               UUID PRIMARY KEY,
        name             VARCHAR(128) NOT NULL UNIQUE,
        display_name     VARCHAR(256) NOT NULL DEFAULT '',
        database_name    VARCHAR(128) NOT NULL DEFAULT '',
        db_type          VARCHAR(32)  NOT NULL DEFAULT 'mysql',
        datasource       VARCHAR(128) NOT NULL DEFAULT '',
        source_table     JSONB        NOT NULL DEFAULT '[]',
        primary_table    VARCHAR(128) NOT NULL DEFAULT '',
        join_clause      TEXT         NOT NULL DEFAULT '',
        fields           JSONB        NOT NULL DEFAULT '{}',
        query_constraint JSONB        NOT NULL DEFAULT '{}',
        enabled          BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
    );

    -- 迁移：为已有表添加新列（幂等）
    DO $$ BEGIN
        ALTER TABLE entity_definition ADD COLUMN IF NOT EXISTS db_type VARCHAR(32) NOT NULL DEFAULT 'mysql';
        ALTER TABLE entity_definition ADD COLUMN IF NOT EXISTS datasource VARCHAR(128) NOT NULL DEFAULT '';
    EXCEPTION WHEN OTHERS THEN NULL;
    END $$;

    CREATE TABLE IF NOT EXISTS query_audit_log (
        id            UUID PRIMARY KEY,
        entity        VARCHAR(128) NOT NULL DEFAULT '',
        dsl           JSONB        NOT NULL DEFAULT '{}',
        sql_generated TEXT         NOT NULL DEFAULT '',
        result_count  INTEGER      NOT NULL DEFAULT 0,
        duration_ms   INTEGER      NOT NULL DEFAULT 0,
        status        VARCHAR(16)  NOT NULL DEFAULT 'success',
        error_msg     TEXT         NOT NULL DEFAULT '',
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_query_audit_time
        ON query_audit_log (created_at DESC);

    CREATE TABLE IF NOT EXISTS audit_log (
        id            UUID PRIMARY KEY,
        operator      VARCHAR(128) NOT NULL DEFAULT '',
        tool_name     VARCHAR(128) NOT NULL DEFAULT '',
        parameter     JSONB        NOT NULL DEFAULT '{}',
        result_count  INTEGER      NOT NULL DEFAULT 0,
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_lens_audit_time
        ON audit_log (created_at DESC);
    """
    async with _pool.acquire() as conn:
        await conn.execute(ddl)
    logger.info("数据库表结构已就绪")


# ── Entity Definition Repository ──────────────────


async def save_entity(
    name: str,
    display_name: str = "",
    database_name: str = "",
    db_type: str = "mysql",
    datasource: str = "",
    source_table: list[str] | None = None,
    primary_table: str = "",
    join_clause: str = "",
    fields: dict | None = None,
    query_constraint: dict | None = None,
    enabled: bool = True,
) -> str:
    """UPSERT entity definition，返回 id。"""
    pool = get_pool()
    if not pool:
        return ""
    eid = str(uuid.uuid4())
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO entity_definition (
                id, name, display_name, database_name, db_type, datasource,
                source_table, primary_table, join_clause, fields,
                query_constraint, enabled, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10::jsonb, $11::jsonb, $12, now(), now())
            ON CONFLICT (name) DO UPDATE SET
                display_name     = EXCLUDED.display_name,
                database_name    = EXCLUDED.database_name,
                db_type          = EXCLUDED.db_type,
                datasource       = EXCLUDED.datasource,
                source_table     = EXCLUDED.source_table,
                primary_table    = EXCLUDED.primary_table,
                join_clause      = EXCLUDED.join_clause,
                fields           = EXCLUDED.fields,
                query_constraint = EXCLUDED.query_constraint,
                enabled          = EXCLUDED.enabled,
                updated_at       = now()
            RETURNING id
            """,
            uuid.UUID(eid),
            name,
            display_name,
            database_name,
            db_type,
            datasource,
            json.dumps(source_table or [], ensure_ascii=False),
            primary_table,
            join_clause,
            json.dumps(fields or {}, ensure_ascii=False),
            json.dumps(query_constraint or {}, ensure_ascii=False),
            enabled,
        )
    return str(row["id"]) if row else eid


async def get_entity(name: str) -> dict | None:
    """按名称获取 entity definition。"""
    pool = get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM entity_definition WHERE name = $1",
            name,
        )
    if not row:
        return None
    return _row_to_entity_dict(row)


async def list_entities(enabled_only: bool = True) -> list[dict]:
    """列出所有 entity definition。"""
    pool = get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        if enabled_only:
            rows = await conn.fetch(
                "SELECT * FROM entity_definition WHERE enabled = TRUE ORDER BY name"
            )
        else:
            rows = await conn.fetch("SELECT * FROM entity_definition ORDER BY name")
    return [_row_to_entity_dict(r) for r in rows]


async def delete_entity(name: str) -> bool:
    """删除 entity definition。"""
    pool = get_pool()
    if not pool:
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM entity_definition WHERE name = $1", name
        )
    return int(result.split()[-1]) > 0


def _safe_get(row, key: str, default=None):
    """安全获取 asyncpg Record 或 dict 的值"""
    try:
        return row[key]
    except (KeyError, Exception):
        return default


def _row_to_entity_dict(row) -> dict:
    """将 asyncpg Record 转为 dict。"""
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "display_name": row["display_name"],
        "database_name": row["database_name"],
        "db_type": _safe_get(row, "db_type", "mysql"),
        "datasource": _safe_get(row, "datasource", ""),
        "source_table": (
            json.loads(row["source_table"])
            if isinstance(row["source_table"], str)
            else row["source_table"]
        ),
        "primary_table": row["primary_table"],
        "join_clause": row["join_clause"],
        "fields": (
            json.loads(row["fields"])
            if isinstance(row["fields"], str)
            else row["fields"]
        ),
        "query_constraint": (
            json.loads(row["query_constraint"])
            if isinstance(row["query_constraint"], str)
            else row["query_constraint"]
        ),
        "enabled": row["enabled"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ── Query Audit Log Repository ────────────────────


async def save_query_audit(
    entity: str = "",
    dsl: dict | None = None,
    sql_generated: str = "",
    result_count: int = 0,
    duration_ms: int = 0,
    status: str = "success",
    error_msg: str = "",
) -> str:
    """记录查询审计日志。"""
    pool = get_pool()
    if not pool:
        return ""
    qid = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO query_audit_log (
                id, entity, dsl, sql_generated, result_count,
                duration_ms, status, error_msg, created_at
            ) VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, now())
            """,
            uuid.UUID(qid),
            entity,
            json.dumps(dsl or {}, ensure_ascii=False),
            sql_generated,
            result_count,
            duration_ms,
            status,
            error_msg,
        )
    return qid


# ── Audit Log Repository ──────────────────────────


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
