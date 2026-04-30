"""查询服务 — DSL 查询的入口

负责：验证 DSL → 编译 SQL → 选择适配器 → 执行查询 → 审计记录 → 返回结果。
"""

import logging
import time

from app.adapters import pg_adapter, registry
from app.core.config import get_settings
from app.schemas.query import QueryDSL, QueryResult, ValidationResult
from app.services.dsl_compiler import compile_to_sql, validate_dsl
from app.services.entity_service import get_entity_definition

logger = logging.getLogger("lens.query")


def _resolve_adapter(entity):
    """根据 entity 的 datasource / db_type 找到对应适配器"""
    # 优先按 datasource 名称查找
    if entity.datasource:
        adapter = registry.get(entity.datasource)
        if adapter:
            return adapter
        logger.warning(
            "Entity '%s' 指定的 datasource '%s' 未注册，尝试按 db_type 查找",
            entity.name, entity.datasource,
        )

    # 按 db_type 查找
    adapter = registry.get_by_type(entity.db_type)
    if adapter:
        return adapter

    # 兜底：默认适配器
    return registry.get_default()


async def execute_dsl_query(dsl: QueryDSL) -> QueryResult:
    """执行 DSL 查询的完整流程。"""
    start = time.monotonic()

    # 1. 获取 entity definition
    entity = await get_entity_definition(dsl.entity)
    if not entity:
        return QueryResult(
            success=False,
            error=f"业务对象 '{dsl.entity}' 不存在或未启用",
        )

    if not entity.enabled:
        return QueryResult(
            success=False,
            error=f"业务对象 '{dsl.entity}' 已禁用",
        )

    # 2. 验证 DSL
    validation = validate_dsl(dsl, entity)
    if not validation.valid:
        return QueryResult(
            success=False,
            error="; ".join(validation.errors),
        )

    # 3. 编译 SQL
    try:
        sql, params = compile_to_sql(dsl, entity)
    except ValueError as e:
        return QueryResult(success=False, error=f"SQL 编译失败: {e}")

    # 4. 选择适配器
    adapter = _resolve_adapter(entity)
    if not adapter:
        return QueryResult(
            success=False,
            error=f"业务对象 '{dsl.entity}' 没有可用的数据库适配器（db_type={entity.db_type}）",
        )

    # 5. 执行查询
    cfg = get_settings().query
    if hasattr(adapter, "execute_dsl_query"):
        rows = await adapter.execute_dsl_query(dsl, entity)
    else:
        rows = await adapter.execute_readonly_query(sql, params, timeout=cfg.timeout_seconds)
    duration_ms = int((time.monotonic() - start) * 1000)

    # 6. 记录查询审计
    try:
        await pg_adapter.save_query_audit(
            entity=dsl.entity,
            dsl=dsl.model_dump(),
            sql_generated=sql,
            result_count=len(rows),
            duration_ms=duration_ms,
            status="success",
        )
    except Exception:
        logger.warning("查询审计写入失败", exc_info=True)

    return QueryResult(
        success=True,
        data=rows,
        count=len(rows),
        sql=sql,
        duration_ms=duration_ms,
    )


async def validate_dsl_query(dsl: QueryDSL) -> ValidationResult:
    """验证 DSL 查询但不执行。"""
    entity = await get_entity_definition(dsl.entity)
    if not entity:
        return ValidationResult(
            valid=False,
            errors=[f"业务对象 '{dsl.entity}' 不存在"],
        )

    return validate_dsl(dsl, entity)
