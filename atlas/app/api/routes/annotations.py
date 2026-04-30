"""语义标注 REST API

供 Console 前端管理语义标注 — 查看、添加、确认、统计。
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.annotation_service import (
    batch_annotate,
    confirm_annotation,
    confirm_annotations,
    get_annotation_stats,
    list_pending_annotations,
    save_annotation,
    search_annotations,
)

router = APIRouter(prefix="/annotations", tags=["annotations"])


class AnnotateRequest(BaseModel):
    database: str
    table: str
    column: str
    semantic: str
    source: str = "manual"


class ConfirmRequest(BaseModel):
    database: str
    table: str
    column: str
    confirmed: bool = True


class BatchConfirmRequest(BaseModel):
    annotations: list[dict]
    confirmed: bool = True


class BatchAnnotateRequest(BaseModel):
    annotations: list[dict]
    source: str = "ai"


@router.get("/{database}")
async def list_annotations(
    database: str,
    table: str | None = None,
    q: str = "",
    source: str = "",
    confirmed: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """分页列出指定数据库（或表）的语义标注。"""
    result = await search_annotations(
        database=database,
        table=table,
        q=q,
        source=source,
        confirmed=confirmed,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(result["annotations"]),
        "total": result["total"],
        "limit": limit,
        "offset": offset,
        "annotations": result["annotations"],
    }


@router.get("/{database}/pending")
async def pending_annotations(database: str):
    """列出待确认的语义标注"""
    result = await list_pending_annotations(database)
    return {"count": len(result), "annotations": result}


@router.get("/{database}/stats")
async def annotation_stats(database: str):
    """语义标注覆盖率统计"""
    return await get_annotation_stats(database)


@router.post("/annotate")
async def annotate(req: AnnotateRequest):
    """添加或更新单条语义标注"""
    annotation_id = await save_annotation(
        database=req.database,
        table=req.table,
        column=req.column,
        semantic=req.semantic,
        source=req.source,
    )
    return {"id": annotation_id, "status": "saved"}


@router.post("/confirm")
async def confirm(req: ConfirmRequest):
    """确认或拒绝语义标注"""
    ok = await confirm_annotation(
        database=req.database,
        table=req.table,
        column=req.column,
        confirmed=req.confirmed,
    )
    return {"confirmed": req.confirmed, "success": ok}


@router.post("/confirm-batch")
async def confirm_batch(req: BatchConfirmRequest):
    """批量确认或驳回标注"""
    result = await confirm_annotations(
        annotations=req.annotations,
        confirmed=req.confirmed,
    )
    return {"confirmed": req.confirmed, **result}


@router.post("/batch")
async def batch(req: BatchAnnotateRequest):
    """批量语义标注"""
    result = await batch_annotate(
        annotations=req.annotations,
        source=req.source,
    )
    return result
