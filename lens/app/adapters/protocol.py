"""业务数据库适配器协议

所有业务数据源（MySQL、PostgreSQL 等）的查询适配器必须实现此协议。
Service 层只依赖 Protocol，不依赖具体实现。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class BusinessDBAdapter(Protocol):
    """业务数据库只读查询适配器协议"""

    @property
    def name(self) -> str:
        """适配器名称（用于日志和注册表 key）"""
        ...

    @property
    def db_type(self) -> str:
        """数据库类型标识（mysql / postgresql）"""
        ...

    async def init_pool(self) -> None:
        """初始化连接池"""
        ...

    async def close_pool(self) -> None:
        """关闭连接池"""
        ...

    async def execute_readonly_query(
        self,
        sql: str,
        params: tuple | None = None,
        timeout: int = 30,
    ) -> list[dict]:
        """执行只读 SELECT 查询，返回字典列表。

        安全约束：
        - SQL 必须以 SELECT 开头
        - 必须包含 LIMIT
        - 适配器不可用时返回空列表，不抛异常
        """
        ...

    async def get_table_row_count(self, database: str, table: str) -> int:
        """获取表的近似行数（用于 validate 的影响评估）。

        返回 -1 表示无法获取。
        """
        ...
