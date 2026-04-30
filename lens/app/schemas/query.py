"""Lens 数据模型 — DSL 查询、业务对象定义、风控约束"""

from pydantic import BaseModel, Field
from typing import Any, Literal


class FilterCondition(BaseModel):
    """单个筛选条件"""

    field: str
    op: str = "eq"  # eq, ne, gt, gte, lt, lte, in, like, between
    value: Any = None


class TimeRange(BaseModel):
    """时间范围约束"""

    start: str | None = None  # ISO 日期格式，如 2026-03-01
    end: str | None = None


class QueryDSL(BaseModel):
    """结构化查询 DSL — AI 只表达查询意图，Lens 决定怎么查"""

    entity: str
    filter: list[FilterCondition] = []
    field: list[str] | None = None
    aggregate: Literal["count"] | None = None
    order_by: str | None = None  # 字段名，前缀 "-" 表示 DESC
    limit: int = Field(default=20, ge=1, le=100)
    time_range: TimeRange | None = None


class QueryResult(BaseModel):
    """查询结果"""

    success: bool = True
    data: list[dict] = []
    count: int = 0
    sql: str = ""  # 生成的 SQL（审计用，不暴露给 AI）
    duration_ms: int = 0
    error: str = ""


class ValidationResult(BaseModel):
    """DSL 验证结果"""

    valid: bool = True
    errors: list[str] = []
    warnings: list[str] = []


class EntityField(BaseModel):
    """业务对象的字段定义"""

    name: str  # 字段名（逻辑名，暴露给 AI）
    column: str = ""  # 实际物理列名（不暴露给 AI）
    type: str = ""  # 数据类型
    semantic: str = ""  # 语义描述
    filterable: bool = True  # 是否可作为筛选条件
    sortable: bool = True  # 是否可排序
    sensitive: bool = False  # 是否敏感字段（需脱敏）
    default_visible: bool = True  # 是否默认返回


class EntityConstraint(BaseModel):
    """业务对象的风控约束"""

    time_field: str = ""  # 用于时间范围约束的字段名
    default_time_range_days: int = 7
    required_filter_fields: list[str] = []  # 必须指定的筛选字段


class EntityDefinition(BaseModel):
    """业务对象定义 — entity_definition 表的内存表示"""

    id: str = ""
    name: str  # 业务对象名称（如 order）
    display_name: str = ""  # 显示名称（如 订单）
    database: str = ""  # 所在数据库
    db_type: str = "mysql"  # 数据库类型（mysql / postgresql）
    datasource: str = ""  # 数据源名称（对应 registry 中的 adapter name）
    source_table: list[str] = []  # 映射的物理表
    primary_table: str = ""  # 主表（如果有多张表）
    join_clause: str = ""  # JOIN 子句（如果需要关联多张表）
    fields: dict[str, EntityField] = {}  # 字段映射
    constraint: EntityConstraint = EntityConstraint()
    enabled: bool = True
