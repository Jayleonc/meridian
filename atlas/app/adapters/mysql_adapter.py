"""MySQL 适配器 — 从业务 MySQL 的 information_schema 采集表结构

只读连接，使用连接池管理，不执行任何写操作。
"""

import logging
from typing import Optional

import aiomysql

from app.core.config import get_settings
from app.schemas.metadata import ColumnInfo, TableInfo

logger = logging.getLogger(__name__)

# ── 连接池管理 ─────────────────────────────────

_pool: Optional[aiomysql.Pool] = None


async def init_pool() -> None:
    """创建连接池（应用启动时调用）"""
    global _pool
    if _pool is not None:
        return

    cfg = get_settings().business_mysql
    try:
        _pool = await aiomysql.create_pool(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            charset="utf8mb4",
            minsize=1,
            maxsize=10,
            autocommit=True,
            # 连接 information_schema 作为默认 db，查询时通过 TABLE_SCHEMA 过滤
            db="information_schema",
        )
        logger.info("MySQL connection pool created: %s:%s", cfg.host, cfg.port)
    except (aiomysql.Error, ConnectionRefusedError, OSError) as exc:
        logger.error("Failed to create MySQL connection pool: %s", exc)
        _pool = None


def get_pool() -> Optional[aiomysql.Pool]:
    """获取当前连接池（可能为 None）"""
    return _pool


async def close_pool() -> None:
    """关闭连接池（应用关闭时调用）"""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("MySQL connection pool closed")


# ── 数据采集 ─────────────────────────────────


async def fetch_tables(database: str) -> list[TableInfo]:
    """从 information_schema 获取指定数据库的所有表信息"""
    if _pool is None:
        logger.warning("Connection pool not available, cannot fetch tables for %s", database)
        return []

    try:
        async with _pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT TABLE_NAME, TABLE_COMMENT, ENGINE, TABLE_ROWS, CREATE_TIME
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                    """,
                    (database,),
                )
                rows = await cur.fetchall()

                tables = []
                for row in rows:
                    table = TableInfo(
                        database=database,
                        name=row["TABLE_NAME"],
                        comment=row.get("TABLE_COMMENT", ""),
                        engine=row.get("ENGINE", ""),
                        row_count_approx=row.get("TABLE_ROWS", 0) or 0,
                        create_time=str(row.get("CREATE_TIME", "")),
                    )
                    tables.append(table)

                return tables
    except (aiomysql.Error, ConnectionRefusedError, OSError) as exc:
        logger.warning("Failed to fetch tables for database '%s': %s", database, exc)
        return []


async def fetch_columns(database: str, table_name: str) -> list[ColumnInfo]:
    """从 information_schema 获取指定表的字段信息"""
    if _pool is None:
        logger.warning(
            "Connection pool not available, cannot fetch columns for %s.%s",
            database,
            table_name,
        )
        return []

    try:
        async with _pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_COMMENT,
                           COLUMN_KEY, EXTRA
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (database, table_name),
                )
                col_rows = await cur.fetchall()

                columns = []
                for row in col_rows:
                    col = ColumnInfo(
                        name=row["COLUMN_NAME"],
                        type=row["COLUMN_TYPE"],
                        nullable=row["IS_NULLABLE"] == "YES",
                        comment=row.get("COLUMN_COMMENT", ""),
                        is_primary_key=row.get("COLUMN_KEY") == "PRI",
                        is_index=row.get("COLUMN_KEY", "") in ("PRI", "MUL", "UNI"),
                    )
                    columns.append(col)

                return columns
    except (aiomysql.Error, ConnectionRefusedError, OSError) as exc:
        logger.warning(
            "Failed to fetch columns for %s.%s: %s", database, table_name, exc
        )
        return []


async def fetch_full_schema(database: str) -> list[TableInfo]:
    """获取完整 schema（表 + 字段），用于生成快照

    受 settings.limits.max_tables 限制，超出部分忽略并记录日志。
    """
    settings = get_settings()
    max_tables = settings.limits.max_tables

    tables = await fetch_tables(database)
    if not tables:
        return tables

    if len(tables) > max_tables:
        logger.warning(
            "Database '%s' has %d tables, exceeding limit %d. Truncating.",
            database,
            len(tables),
            max_tables,
        )
        tables = tables[:max_tables]

    for table in tables:
        table.column = await fetch_columns(database, table.name)

    return tables
