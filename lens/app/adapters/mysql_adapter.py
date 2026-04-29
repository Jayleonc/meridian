"""MySQL 业务数据库适配器

实现 BusinessDBAdapter 协议。连接业务 MySQL，只执行 SELECT 查询。
"""

import logging
import re

import aiomysql

logger = logging.getLogger("lens.mysql")

_MUTATING_SQL_RE = re.compile(
    r"\b("
    r"ALTER|ANALYZE|CALL|CREATE|DELETE|DROP|GRANT|INSERT|LOAD|LOCK|"
    r"OPTIMIZE|RENAME|REPLACE|REVOKE|SET|TRUNCATE|UNLOCK|UPDATE"
    r")\b",
    re.IGNORECASE,
)


def _readonly_rejection_reason(sql: str) -> str | None:
    stripped = sql.strip()
    if not stripped:
        return "空 SQL"

    body = stripped[:-1].strip() if stripped.endswith(";") else stripped
    if ";" in body:
        return "多语句 SQL"

    sql_upper = body.upper()
    if not sql_upper.startswith("SELECT"):
        return "非 SELECT 查询"

    if _MUTATING_SQL_RE.search(body):
        return "包含写入或管理类 SQL 关键字"

    if "LIMIT" not in sql_upper:
        return "没有 LIMIT 的查询"

    return None


class MySQLAdapter:
    """MySQL 只读查询适配器"""

    def __init__(
        self,
        *,
        adapter_name: str = "mysql",
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = "readonly",
        password: str = "",
        databases: list[str] | None = None,
        min_pool: int = 1,
        max_pool: int = 10,
    ):
        self._name = adapter_name
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._databases = databases or []
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._pool: aiomysql.Pool | None = None

    @property
    def pool(self) -> aiomysql.Pool | None:
        return self._pool

    @property
    def name(self) -> str:
        return self._name

    @property
    def db_type(self) -> str:
        return "mysql"

    async def init_pool(self) -> None:
        if self._pool is not None:
            return

        if not self._databases:
            logger.warning("[%s] 未配置业务数据库，跳过连接池初始化", self._name)
            return

        try:
            self._pool = await aiomysql.create_pool(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                charset="utf8mb4",
                minsize=self._min_pool,
                maxsize=self._max_pool,
                autocommit=True,
            )
            logger.info("[%s] MySQL 连接池已创建: %s:%s", self._name, self._host, self._port)
        except (aiomysql.Error, ConnectionRefusedError, OSError) as exc:
            logger.error("[%s] 创建 MySQL 连接池失败: %s", self._name, exc)
            self._pool = None

    async def close_pool(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.info("[%s] MySQL 连接池已关闭", self._name)

    async def execute_readonly_query(
        self,
        sql: str,
        params: tuple | None = None,
        timeout: int = 30,
    ) -> list[dict]:
        if self._pool is None:
            logger.warning("[%s] MySQL 连接池不可用", self._name)
            return []

        rejection_reason = _readonly_rejection_reason(sql)
        if rejection_reason is not None:
            logger.error("[%s] 拒绝执行 %s: %s", self._name, rejection_reason, sql[:100])
            return []

        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(sql, params or ())
                    rows = await cur.fetchall()
                    return list(rows)
        except aiomysql.OperationalError as exc:
            logger.warning("[%s] 查询执行失败 (OperationalError): %s", self._name, exc)
            return []
        except (aiomysql.Error, ConnectionRefusedError, OSError) as exc:
            logger.warning("[%s] 查询执行失败: %s", self._name, exc)
            return []

    async def get_table_row_count(self, database: str, table: str) -> int:
        if self._pool is None:
            return -1
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        """
                        SELECT TABLE_ROWS
                        FROM information_schema.TABLES
                        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                        """,
                        (database, table),
                    )
                    row = await cur.fetchone()
                    return row["TABLE_ROWS"] if row else -1
        except Exception as exc:
            logger.warning("[%s] 获取行数失败 %s.%s: %s", self._name, database, table, exc)
            return -1


# ── 向后兼容：模块级函数委托到默认实例 ──────────────────
# 保留给 main.py lifespan 和旧调用方使用，Phase 2 会移除

_default: MySQLAdapter | None = None


async def init_pool() -> None:
    global _default
    from app.core.config import get_settings
    cfg = get_settings().business_mysql
    _default = MySQLAdapter(
        adapter_name="default-mysql",
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        databases=cfg.database,
    )
    await _default.init_pool()


async def close_pool() -> None:
    global _default
    if _default:
        await _default.close_pool()
        _default = None


async def execute_readonly_query(
    sql: str,
    params: tuple | None = None,
    timeout: int = 30,
) -> list[dict]:
    if _default is None:
        logger.warning("MySQL 连接池不可用（默认实例未初始化）")
        return []
    return await _default.execute_readonly_query(sql, params, timeout)


async def get_table_row_count(database: str, table: str) -> int:
    if _default is None:
        return -1
    return await _default.get_table_row_count(database, table)


def get_pool() -> aiomysql.Pool | None:
    return _default.pool if _default else None
