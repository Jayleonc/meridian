"""Lens MCP 工具定义

四个核心工具：
- list_entity: 列出所有可查询的业务对象
- describe_entity: 描述业务对象的结构和可查询字段
- query: 通过结构化 DSL 查询业务数据
- validate: 验证 DSL 查询是否合法（不执行）
"""

import json

from mcp.server.fastmcp import FastMCP

from app.schemas.query import FilterCondition, QueryDSL, TimeRange
from app.services.entity_service import get_entity_definition, list_entity_definitions
from app.services.query_service import execute_dsl_query, validate_dsl_query
from app.utils.audit import audited

mcp = FastMCP("lens")


@mcp.tool()
@audited("list_entity")
async def list_entity() -> str:
    """列出所有可查询的业务对象。

    返回业务对象名称、显示名称和字段数量。
    """
    entities = await list_entity_definitions()
    result = [
        {
            "name": e.name,
            "display_name": e.display_name,
            "field_count": len(e.fields),
            "database": e.database,
            "db_type": e.db_type,
        }
        for e in entities
    ]
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
@audited("describe_entity")
async def describe_entity(entity: str) -> str:
    """描述一个业务对象的结构和可查询字段。

    返回字段列表，包含语义描述、数据类型、是否可筛选、是否可排序。
    不暴露物理表结构，只暴露逻辑字段。
    """
    definition = await get_entity_definition(entity)
    if not definition:
        return json.dumps(
            {"error": f"业务对象 '{entity}' 不存在"},
            ensure_ascii=False,
        )

    fields = []
    for fname, fdef in definition.fields.items():
        fields.append({
            "name": fname,
            "type": fdef.type,
            "semantic": fdef.semantic,
            "filterable": fdef.filterable,
            "sortable": fdef.sortable,
            "sensitive": fdef.sensitive,
            "default_visible": fdef.default_visible,
        })

    result = {
        "name": definition.name,
        "display_name": definition.display_name,
        "fields": fields,
        "constraint": {
            "time_field": definition.constraint.time_field,
            "default_time_range_days": definition.constraint.default_time_range_days,
            "required_filter_fields": definition.constraint.required_filter_fields,
        },
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
@audited("query")
async def query(
    entity: str,
    filter: list[dict] | None = None,
    field: list[str] | None = None,
    preview: bool = False,
    order_by: str | None = None,
    limit: int = 20,
    time_range: dict | None = None,
) -> str:
    """通过结构化 DSL 查询业务数据。AI 不写 SQL，只表达查询意图。

    参数：
    - entity: 业务对象名称（如 "order"）
    - filter: 筛选条件列表，每个为 {"field": "xxx", "op": "eq", "value": "yyy"}
      支持操作符: eq, ne, gt, gte, lt, lte, in, like, between
    - field: 要返回的字段列表（不传返回默认字段集）
    - preview: 预览样本模式；只返回默认安全字段，最多返回配置的 preview_limit 行
    - order_by: 排序字段，前缀 "-" 表示降序（如 "-created_at"）
    - limit: 返回条数，默认 20，最大 100
    - time_range: 时间范围 {"start": "2026-03-01", "end": "2026-03-19"}
    """
    # 构建 QueryDSL
    filters = [FilterCondition(**f) for f in (filter or [])]
    tr = TimeRange(**time_range) if time_range else None

    dsl = QueryDSL(
        entity=entity,
        filter=filters,
        field=field,
        preview=preview,
        order_by=order_by,
        limit=min(limit, 100),
        time_range=tr,
    )

    result = await execute_dsl_query(dsl)

    # 不暴露 SQL 给 AI
    output = {
        "success": result.success,
        "data": result.data,
        "count": result.count,
        "duration_ms": result.duration_ms,
    }
    if result.error:
        output["error"] = result.error

    return json.dumps(output, ensure_ascii=False, default=str)


@mcp.tool()
@audited("validate")
async def validate(
    entity: str,
    filter: list[dict] | None = None,
    field: list[str] | None = None,
    preview: bool = False,
    order_by: str | None = None,
    limit: int = 20,
) -> str:
    """验证一个 DSL 查询是否合法，不实际执行。

    返回是否合法、错误原因列表和警告信息。
    """
    filters = [FilterCondition(**f) for f in (filter or [])]

    dsl = QueryDSL(
        entity=entity,
        filter=filters,
        field=field,
        preview=preview,
        order_by=order_by,
        limit=min(limit, 100),
    )

    result = await validate_dsl_query(dsl)
    return json.dumps(result.model_dump(), ensure_ascii=False)
