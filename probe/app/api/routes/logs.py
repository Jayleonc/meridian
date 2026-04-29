"""日志查询 REST API

供 Console 前端通过 HTTP 调用 Probe 日志查询能力。
"""

from fastapi import APIRouter, Query

from app.services.log_service import (
    get_context,
    get_services,
    search_by_request_id,
    search_logs,
    tail_errors,
)

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/services")
async def list_services():
    """列出可观测的服务"""
    return await get_services()


@router.get("/errors")
async def errors(
    hours_back: int = Query(1, ge=1, le=24),
    keyword: str | None = Query(None),
    limit: int = Query(30, ge=1, le=500),
):
    """查看最近的错误日志"""
    result = await tail_errors(hours_back=hours_back, keyword=keyword, limit=limit)
    return result.model_dump()


@router.post("/search")
async def search(body: dict):
    """按关键词搜索日志"""
    result = await search_logs(
        keyword=body["keyword"],
        start_time=body.get("start_time"),
        end_time=body.get("end_time"),
        level=body.get("level"),
        limit=body.get("limit", 20),
    )
    return result.model_dump()


@router.get("/context")
async def context(
    file: str,
    line_number: int = Query(..., ge=1),
    before: int = Query(10, ge=0, le=50),
    after: int = Query(10, ge=0, le=50),
):
    """查看某条日志前后的上下文。"""
    return get_context(file, line_number, before, after)


@router.get("/trace/{request_id}")
async def trace(
    request_id: str,
    back_hours: int = Query(0, ge=0, le=72),
    hint_time: str | None = Query(None),
):
    """按 request_id 追踪请求链路"""
    result = await search_by_request_id(
        request_id=request_id,
        back_hours=back_hours,
        hint_time=hint_time,
    )
    return result.model_dump()
