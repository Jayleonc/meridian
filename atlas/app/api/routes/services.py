"""服务发现 REST API

供 Probe 等内部服务通过 HTTP 获取服务列表。
"""

from fastapi import APIRouter

from app.services.service_discovery import get_service_detail, get_services, refresh_services

router = APIRouter(prefix="/services", tags=["services"])


@router.get("")
async def list_services():
    """列出所有已发现的服务"""
    services = await get_services()
    return {
        "count": len(services),
        "service": [svc.model_dump() for svc in services],
    }


@router.post("/refresh")
async def refresh():
    """强制刷新服务列表"""
    services = await refresh_services()
    return {
        "count": len(services),
        "service": [svc.model_dump() for svc in services],
    }


@router.get("/{name}")
async def get_service(name: str):
    """获取指定服务详情"""
    svc = await get_service_detail(name)
    if not svc:
        return {"error": f"服务 '{name}' 不存在"}
    return svc.model_dump()
