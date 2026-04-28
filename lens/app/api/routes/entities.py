"""业务对象 REST API

供 Console 前端通过 HTTP 调用 Lens 查询能力。
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.schemas.query import QueryDSL
from app.services.entity_service import (
    delete_entity_definition,
    get_entity_definition,
    list_entity_definitions,
)
from app.services.entity_generator import import_from_atlas
from app.services.query_service import execute_dsl_query, validate_dsl_query

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("")
async def list_entities():
    """列出所有可查询的业务对象"""
    entities = await list_entity_definitions(enabled_only=True)
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
    """执行 DSL 查询"""
    result = await execute_dsl_query(dsl)
    return result.model_dump()


@router.post("/validate")
async def validate(dsl: QueryDSL):
    """验证 DSL 但不执行"""
    result = await validate_dsl_query(dsl)
    return result.model_dump()


class ImportRequest(BaseModel):
    database: str = ""
    atlas_url: str = "http://127.0.0.1:3001"
    db_type: str = "mysql"
    datasource: str = ""
    overwrite: bool = False


@router.post("/import-from-atlas")
async def import_entities(req: ImportRequest):
    """从 Atlas schema 自动生成业务实体定义

    调用 Atlas REST API 获取数据库 schema，为每张表自动生成 EntityDefinition:
    - 自动识别 filterable/sortable/sensitive 字段
    - 自动检测 time_field（created_at, create_time 等）
    - 自动映射 MySQL/PG 类型到 Lens 语义类型
    """
    result = await import_from_atlas(
        database=req.database or None,
        atlas_url=req.atlas_url,
        db_type=req.db_type,
        datasource=req.datasource,
        overwrite=req.overwrite,
    )
    return result


@router.delete("/{name}")
async def delete_entity(name: str):
    """删除业务对象定义"""
    deleted = await delete_entity_definition(name)
    if not deleted:
        return {"error": f"业务对象 '{name}' 不存在", "deleted": False}
    return {"deleted": True, "name": name}
