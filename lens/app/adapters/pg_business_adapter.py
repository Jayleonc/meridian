"""PostgreSQL 业务数据库适配器

实现 BusinessDBAdapter 协议。连接业务 PostgreSQL，只执行 SELECT 查询。
注意：这是业务 PG，不是 Meridian 平台 PG（pg_adapter.py）。
"""

import logging

import asyncpg

logger = logging.getLogger("lens.pg_business")


class PostgreSQLAdapter:
    """PostgreSQL 只读查询适配器"""

    def __init__(
        self,
        *,
        adapter_name: str = "postgresql",
        host: str = "127.0.0.1",
        port: int = 5432,
        user: str = "readonly",
        password: str = "",
        database: str = "",
        min_pool: int = 2,
        max_pool: int = 10,
    ):
        self._name = adapter_name
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._pool: asyncpg.Pool | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def db_type(self) -> str:
        return "postgresql"

    async def init_pool(self) -> None:
        if self._pool is not None:
            return

        if not self._database:
            logger.warning("[%s] 未配置数据库名称，跳过连接池初始化", self._name)
            return

        try:
            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                min_size=self._min_pool,
                max_size=self._max_pool,
            )
            logger.info(
                "[%s] PostgreSQL 连接池已创建: %s:%s/%s",
                self._name, self._host, self._port, self._database,
            )
        except (asyncpg.PostgresError, ConnectionRefusedError, OSError) as exc:
            logger.error("[%s] 创建 PostgreSQL 连接池失败: %s", self._name, exc)
            self._pool = None

    async def close_pool(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("[%s] PostgreSQL 连接池已关闭", self._name)

    async def execute_readonly_query(
        self,
        sql: str,
        params: tuple | None = None,
        timeout: int = 30,
    ) -> list[dict]:
        if self._pool is None:
            logger.warning("[%s] PostgreSQL 连接池不可用", self._name)
            return []

        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            logger.error("[%s] 拒绝执行非 SELECT 查询: %s", self._name, sql[:100])
            return []

        if "LIMIT" not in sql_upper:
            logger.error("[%s] 拒绝执行没有 LIMIT 的查询: %s", self._name, sql[:100])
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *(params or ()), timeout=timeout)
                return [dict(row) for row in rows]
        except asyncpg.PostgresError as exc:
            logger.warning("[%s] 查询执行失败 (PostgresError): %s", self._name, exc)
            return []
        except (ConnectionRefusedError, OSError) as exc:
            logger.warning("[%s] 查询执行失败: %s", self._name, exc)
            return []

    async def get_table_row_count(self, database: str, table: str) -> int:
        if self._pool is None:
            return -1
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT reltuples::bigint AS estimate
                    FROM pg_class
                    WHERE relname = $1
                    """,
                    table,
                )
                return row["estimate"] if row else -1
        except Exception as exc:
            logger.warning("[%s] 获取行数失败 %s.%s: %s", self._name, database, table, exc)
            return -1
