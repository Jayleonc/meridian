"""DSL → SQL 编译器

将结构化 DSL 查询编译为安全的 SELECT SQL。
支持 MySQL 和 PostgreSQL 两种方言。

核心安全原则：
- 所有值通过参数化查询传递，不拼接字符串
- 强制 LIMIT
- 白名单验证字段名
- 敏感字段自动脱敏
"""

import logging
import re
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.schemas.query import (
    EntityDefinition,
    QueryDSL,
    ValidationResult,
)

logger = logging.getLogger("lens.compiler")

# 合法的字段名模式（防 SQL 注入）
_FIELD_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")

# 支持的操作符映射
_OP_MAP = {
    "eq": "=",
    "ne": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "in": "IN",
    "between": "BETWEEN",
}


# ── SQL 方言 ──────────────────────────────────


class SQLDialect:
    """SQL 方言基类 — 封装不同数据库的语法差异"""

    def placeholder(self, index: int) -> str:
        """参数占位符（index 从 1 开始）"""
        return "%s"

    def quote_id(self, name: str) -> str:
        """标识符引用"""
        return f"`{name}`"

    def mask_expr(self, col: str, alias: str) -> str:
        """敏感字段脱敏表达式"""
        return f"CONCAT(LEFT({col}, 3), '****') AS {self.quote_id(alias)}"

    def qualified_table(self, database: str, table: str) -> str:
        """带库名限定的表名"""
        if database:
            return f"{self.quote_id(database)}.{self.quote_id(table)}"
        return self.quote_id(table)


class MySQLDialect(SQLDialect):
    """MySQL 方言（默认）"""
    pass


class PostgreSQLDialect(SQLDialect):
    """PostgreSQL 方言"""

    def __init__(self):
        self._counter = 0

    def reset(self):
        self._counter = 0

    def placeholder(self, index: int) -> str:
        return f"${index}"

    def quote_id(self, name: str) -> str:
        return f'"{name}"'

    def mask_expr(self, col: str, alias: str) -> str:
        return f"CONCAT(LEFT({col}::text, 3), '****') AS {self.quote_id(alias)}"

    def qualified_table(self, database: str, table: str) -> str:
        # PG 使用 schema 而非 database 限定，一般不需要跨库
        # 如果 database 字段非空，当作 schema 处理
        if database:
            return f"{self.quote_id(database)}.{self.quote_id(table)}"
        return self.quote_id(table)


_DIALECTS = {
    "mysql": MySQLDialect,
    "postgresql": PostgreSQLDialect,
}


def _get_dialect(db_type: str) -> SQLDialect:
    cls = _DIALECTS.get(db_type, MySQLDialect)
    return cls()


# ── 验证（与方言无关）──────────────────────────


def validate_dsl(dsl: QueryDSL, entity: EntityDefinition) -> ValidationResult:
    """验证 DSL 查询是否合法。"""
    errors = []
    warnings = []
    cfg = get_settings().query

    has_time_range = bool(
        dsl.time_range and (dsl.time_range.start or dsl.time_range.end)
    )

    # 1. 明细查询按配置要求收敛范围；count 和 preview 是单独受限模式。
    if (
        cfg.require_filter
        and dsl.aggregate != "count"
        and not dsl.preview
        and not dsl.filter
        and not has_time_range
    ):
        errors.append("必须指定至少一个筛选条件（filter）或时间范围（time_range）")

    if dsl.preview:
        if dsl.aggregate:
            errors.append("预览样本不支持聚合查询")
        if dsl.field:
            errors.append("预览样本只返回默认安全字段，不支持自选返回字段")
        if not _preview_field_names(entity, get_settings().sensitive_fields):
            errors.append("当前实体没有可用于预览的非敏感默认字段")

    # 2. 检查必填筛选字段。count 不要求必填筛选字段。
    filter_fields = {f.field for f in dsl.filter}
    if dsl.aggregate != "count" and not dsl.preview:
        for req_field in entity.constraint.required_filter_fields:
            if req_field not in filter_fields:
                errors.append(f"必须包含筛选字段: {req_field}")

    # 3. 检查字段是否存在
    for fc in dsl.filter:
        if fc.field not in entity.fields:
            errors.append(f"筛选字段不存在: {fc.field}")
        elif not entity.fields[fc.field].filterable:
            errors.append(f"字段不可筛选: {fc.field}")

    # 4. 检查返回字段
    if dsl.field:
        for fname in dsl.field:
            if fname not in entity.fields:
                errors.append(f"返回字段不存在: {fname}")

    # 5. 检查排序字段
    if dsl.order_by:
        sort_field = dsl.order_by.lstrip("-")
        if sort_field not in entity.fields:
            errors.append(f"排序字段不存在: {sort_field}")
        elif not entity.fields[sort_field].sortable:
            errors.append(f"字段不可排序: {sort_field}")

    # 6. 检查操作符
    for fc in dsl.filter:
        if fc.op not in _OP_MAP:
            errors.append(f"不支持的操作符: {fc.op}（支持: {', '.join(_OP_MAP.keys())}）")

    # 7. 检查 limit
    if dsl.limit > cfg.max_limit:
        warnings.append(f"limit 超过最大值 {cfg.max_limit}，将自动截断")
    if dsl.preview and dsl.limit > cfg.preview_limit:
        warnings.append(f"预览样本最多返回 {cfg.preview_limit} 行，将自动截断")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ── 编译 ──────────────────────────────────


def compile_to_sql(
    dsl: QueryDSL,
    entity: EntityDefinition,
) -> tuple[str, tuple]:
    """将 DSL 编译为 SQL + 参数元组。

    根据 entity.db_type 自动选择方言：
    - mysql: %s 占位符，`backtick` 标识符
    - postgresql: $1 占位符，"double-quote" 标识符
    """
    cfg = get_settings()
    sensitive_patterns = cfg.sensitive_fields
    dialect = _get_dialect(entity.db_type)

    # 参数索引计数器（PG 需要 $1, $2...）
    param_idx = [0]

    def next_ph() -> str:
        param_idx[0] += 1
        return dialect.placeholder(param_idx[0])

    # ── SELECT 字段 ──
    select_fields = _build_select_fields(dsl, entity, sensitive_patterns, dialect)

    # ── FROM 子句 ──
    from_clause = _build_from_clause(entity, dialect)

    # ── WHERE 子句 ──
    where_parts, params = _build_where(dsl, entity, dialect, next_ph)

    # ── 自动追加时间范围 ──
    time_parts, time_params = _build_time_range(dsl, entity, cfg.query, dialect, next_ph)
    where_parts.extend(time_parts)
    params.extend(time_params)

    # ── ORDER BY ──
    order_clause = "" if dsl.aggregate == "count" else _build_order_by(dsl, entity, dialect)

    # ── LIMIT ──
    if dsl.aggregate == "count":
        limit = 1
    elif dsl.preview:
        limit = min(dsl.limit, cfg.query.preview_limit, cfg.query.max_limit)
    else:
        limit = min(dsl.limit, cfg.query.max_limit)

    # ── 组装 SQL ──
    sql = f"SELECT {select_fields} FROM {from_clause}"
    if where_parts:
        sql += f" WHERE {' AND '.join(where_parts)}"
    if order_clause:
        sql += f" ORDER BY {order_clause}"
    sql += f" LIMIT {limit}"

    return sql, tuple(params)


def _build_select_fields(
    dsl: QueryDSL,
    entity: EntityDefinition,
    sensitive_patterns: list[str],
    dialect: SQLDialect,
) -> str:
    """构建 SELECT 字段列表，敏感字段自动脱敏。"""
    if dsl.aggregate == "count":
        return "COUNT(*) AS count"

    if dsl.preview:
        field_names = _preview_field_names(entity, sensitive_patterns)
    elif dsl.field:
        field_names = dsl.field
    else:
        field_names = [
            fname
            for fname, fdef in entity.fields.items()
            if fdef.default_visible
        ]

    if not field_names:
        return "*"

    parts = []
    for fname in field_names:
        fdef = entity.fields.get(fname)
        if not fdef:
            continue

        col = fdef.column or fname
        _validate_identifier(col)

        if fdef.sensitive or _is_sensitive(fname, sensitive_patterns):
            parts.append(dialect.mask_expr(col, fname))
        elif col != fname:
            parts.append(f"{dialect.quote_id(col)} AS {dialect.quote_id(fname)}")
        else:
            parts.append(dialect.quote_id(col))

    return ", ".join(parts) if parts else "*"


def _build_from_clause(entity: EntityDefinition, dialect: SQLDialect) -> str:
    """构建 FROM 子句（支持 JOIN）。"""
    if entity.join_clause:
        return entity.join_clause

    primary = entity.primary_table or (entity.source_table[0] if entity.source_table else "")
    if not primary:
        raise ValueError(f"Entity '{entity.name}' 没有配置 source_table")

    _validate_identifier(primary)

    if entity.database:
        _validate_identifier(entity.database)
    return dialect.qualified_table(entity.database, primary)


def _build_where(
    dsl: QueryDSL,
    entity: EntityDefinition,
    dialect: SQLDialect,
    next_ph,
) -> tuple[list[str], list]:
    """构建 WHERE 子句，返回 (条件列表, 参数列表)。"""
    parts = []
    params = []

    for fc in dsl.filter:
        fdef = entity.fields.get(fc.field)
        if not fdef:
            continue

        col = fdef.column or fc.field
        _validate_identifier(col)
        qcol = dialect.quote_id(col)

        if fc.op == "in":
            if not isinstance(fc.value, list) or not fc.value:
                continue
            placeholders = ", ".join([next_ph() for _ in fc.value])
            parts.append(f"{qcol} IN ({placeholders})")
            params.extend(fc.value)
        elif fc.op == "between":
            if not isinstance(fc.value, list) or len(fc.value) != 2:
                continue
            parts.append(f"{qcol} BETWEEN {next_ph()} AND {next_ph()}")
            params.extend(fc.value)
        elif fc.op == "like":
            parts.append(f"{qcol} LIKE {next_ph()}")
            val = fc.value if "%" in str(fc.value) else f"%{fc.value}%"
            params.append(val)
        else:
            sql_op = _OP_MAP.get(fc.op, "=")
            parts.append(f"{qcol} {sql_op} {next_ph()}")
            params.append(fc.value)

    return parts, params


def _build_time_range(
    dsl: QueryDSL,
    entity: EntityDefinition,
    query_cfg,
    dialect: SQLDialect,
    next_ph,
) -> tuple[list[str], list]:
    """构建时间范围约束。"""
    parts = []
    params = []

    time_field = entity.constraint.time_field
    if not time_field:
        return parts, params

    fdef = entity.fields.get(time_field)
    col = fdef.column if fdef else time_field
    _validate_identifier(col)
    qcol = dialect.quote_id(col)

    if dsl.time_range:
        if dsl.time_range.start:
            parts.append(f"{qcol} >= {next_ph()}")
            params.append(dsl.time_range.start)
        if dsl.time_range.end:
            parts.append(f"{qcol} <= {next_ph()}")
            params.append(dsl.time_range.end)
    elif dsl.aggregate == "count":
        return parts, params
    else:
        days = entity.constraint.default_time_range_days or query_cfg.default_time_range_days
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"{qcol} >= {next_ph()}")
        params.append(start)

    return parts, params


def _build_order_by(dsl: QueryDSL, entity: EntityDefinition, dialect: SQLDialect) -> str:
    """构建 ORDER BY 子句。"""
    if not dsl.order_by:
        return ""

    desc = dsl.order_by.startswith("-")
    field_name = dsl.order_by.lstrip("-")

    fdef = entity.fields.get(field_name)
    if not fdef:
        return ""

    col = fdef.column or field_name
    _validate_identifier(col)

    direction = "DESC" if desc else "ASC"
    return f"{dialect.quote_id(col)} {direction}"


def _validate_identifier(name: str) -> None:
    """验证标识符（表名、列名）是否安全。"""
    if not _FIELD_NAME_RE.match(name):
        raise ValueError(f"非法标识符: {name}")


def _is_sensitive(field_name: str, patterns: list[str]) -> bool:
    """检查字段名是否匹配敏感字段模式。"""
    lower = field_name.lower()
    return any(p in lower for p in patterns)


def _preview_field_names(
    entity: EntityDefinition,
    sensitive_patterns: list[str],
) -> list[str]:
    """预览样本只暴露默认可见且非敏感字段。"""
    names = [
        fname
        for fname, fdef in entity.fields.items()
        if fdef.default_visible
        and not fdef.sensitive
        and not _is_sensitive(fname, sensitive_patterns)
    ]
    if names:
        return names[:12]

    return [
        fname
        for fname, fdef in entity.fields.items()
        if not fdef.sensitive and not _is_sensitive(fname, sensitive_patterns)
    ][:8]
