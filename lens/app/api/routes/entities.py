"""业务对象 REST API

供 Console 前端通过 HTTP 调用 Lens 查询能力。
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.schemas.query import QueryDSL
from app.core.config import get_settings
from app.services.entity_service import (
    delete_entity_definition,
    get_entity_definition,
    list_entity_definitions,
    update_entity_definition,
)
from app.services.entity_generator import import_from_atlas
from app.services.query_service import execute_dsl_query, validate_dsl_query

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("")
async def list_entities(include_disabled: bool = Query(False)):
    """列出所有可查询的业务对象"""
    entities = await list_entity_definitions(enabled_only=not include_disabled)
    return {
        "count": len(entities),
        "entity": [
            {
                "name": e.name,
                "display_name": e.display_name,
                "database": e.database,
                "db_type": e.db_type,
                "field_count": len(e.fields),
                "enabled": e.enabled,
                "governed": e.governed,
                "governance_status": "approved" if e.enabled and e.governed else "draft",
            }
            for e in entities
        ],
    }


@router.get("/{name}")
async def describe_entity(name: str):
    """获取业务对象详情"""
    entity = await get_entity_definition(name)
    if not entity:
        return {"error": f"业务对象 '{name}' 不存在"}
    return entity.model_dump()


@router.post("/query")
async def query(dsl: QueryDSL):
    """执行 Agent/MCP 默认 DSL 查询；draft entity 在这里不可查询。"""
    result = await execute_dsl_query(dsl.model_copy(update={"allow_draft": False}))
    return result.model_dump()


@router.post("/operator-query")
async def operator_query(dsl: QueryDSL):
    """执行 Console 运维 DSL 查询；允许查询仍处于 draft 的 entity。"""
    result = await execute_dsl_query(dsl.model_copy(update={"allow_draft": True}))
    return result.model_dump()


@router.post("/validate")
async def validate(dsl: QueryDSL):
    """验证 DSL 但不执行"""
    result = await validate_dsl_query(dsl)
    return result.model_dump()


class ImportRequest(BaseModel):
    database: str = ""
    tables: list[str] = []
    atlas_url: str = ""
    db_type: str = "mysql"
    datasource: str = ""
    overwrite: bool = False
    enabled: bool = False


@router.post("/import-from-atlas")
async def import_entities(req: ImportRequest):
    """从 Atlas schema 自动生成业务实体定义

    调用 Atlas REST API 获取数据库 schema，为每张表自动生成 EntityDefinition:
    - 自动识别 filterable/sortable/sensitive 字段
    - 自动检测 time_field（created_at, create_time 等）
    - 自动映射 MySQL/PG 类型到 Lens 语义类型
    """
    settings = get_settings()
    result = await import_from_atlas(
        database=req.database or None,
        tables=req.tables or None,
        atlas_url=req.atlas_url or settings.atlas_url,
        db_type=req.db_type,
        datasource=req.datasource,
        overwrite=req.overwrite,
        enabled=req.enabled,
    )
    return result


class EntityUpdateRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    fields: dict[str, dict] | None = None
    constraint: dict | None = None


@router.patch("/{name}")
async def update_entity(name: str, req: EntityUpdateRequest):
    """更新 entity 治理配置；启用后才会暴露给 Agent/MCP 查询列表。"""
    entity = await update_entity_definition(
        name=name,
        display_name=req.display_name,
        fields=req.fields,
        constraint=req.constraint,
        enabled=req.enabled,
    )
    if not entity:
        return {"error": f"业务对象 '{name}' 不存在", "updated": False}
    return {"updated": True, "entity": entity.model_dump()}


@router.delete("/{name}")
async def delete_entity(name: str):
    """删除业务对象定义"""
    deleted = await delete_entity_definition(name)
    if not deleted:
        return {"error": f"业务对象 '{name}' 不存在", "deleted": False}
    return {"deleted": True, "name": name}
