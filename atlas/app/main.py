"""Atlas — HTTP 入口

挂载 HTTP 路由和 MCP 传输层。
启动时自动采集一次 schema，可选定时刷新。
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.mysql_adapter import close_pool, init_pool
from app.adapters import pg_adapter
from app.api.routes.annotations import router as annotations_router
from app.api.routes.health import router as health_router
from app.api.routes.schemas import router as schemas_router
from app.api.routes.services import router as services_router
from app.core.config import get_settings
from app.mcp.sse import messages_app as mcp_sse_messages_app
from app.mcp.sse import router as mcp_router

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_refresh_task: asyncio.Task | None = None


def _setup_discovery_providers():
    """根据配置注册服务发现 Provider"""
    from app.adapters.supervisor_adapter import SupervisorProvider
    from app.adapters.static_provider import StaticProvider
    from app.services.service_discovery import register_provider

    cfg = get_settings()

    for provider_name in cfg.discovery.providers:
        if provider_name == "supervisor":
            provider = SupervisorProvider(
                enabled=cfg.supervisor.enabled,
                xmlrpc_url=cfg.supervisor.xmlrpc_url,
                log_dir=cfg.supervisor.log_dir,
            )
            register_provider(provider)
        elif provider_name == "static":
            static_services = [
                svc.model_dump() for svc in cfg.discovery.static_services
            ]
            provider = StaticProvider(services=static_services)
            register_provider(provider)
        else:
            logger.warning("未知的服务发现 Provider: %s", provider_name)


async def _initial_collect():
    """启动后自动采集一次 schema（后台执行，不阻塞启动）"""
    from app.services.schema_service import collect_all

    try:
        snapshots = await collect_all()
        for s in snapshots:
            logger.info("启动采集完成: %s (%d 张表)", s.database, len(s.table))
        if not snapshots:
            logger.warning("启动采集: 没有配置任何业务数据库，或采集失败")
    except Exception:
        logger.error("启动采集失败", exc_info=True)


async def _periodic_refresh(interval_hours: int):
    """定时刷新 schema，检测变更"""
    from app.services.schema_service import collect_all, diff_schema

    interval = interval_hours * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            logger.info("定时刷新: 开始采集...")
            snapshots = await collect_all()
            for s in snapshots:
                logger.info("定时刷新: %s (%d 张表)", s.database, len(s.table))
                # 自动 diff，有变更会写入 changelog
                diff = await diff_schema(s.database)
                if diff and (diff.added_table or diff.removed_table or diff.modified_table):
                    logger.info(
                        "定时刷新: %s 检测到变更 — 新增 %d 表, 删除 %d 表, 修改 %d 表",
                        s.database,
                        len(diff.added_table),
                        len(diff.removed_table),
                        len(diff.modified_table),
                    )
        except Exception:
            logger.error("定时刷新失败", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _refresh_task

    # Startup: initialize connection pools
    await init_pool()
    await pg_adapter.init_pool()

    # 注册服务发现 Provider
    _setup_discovery_providers()

    # 启动后立即采集一次（后台，不阻塞）
    asyncio.create_task(_initial_collect())

    # 如果配置了定时刷新，启动定时任务
    cfg = get_settings()
    if cfg.snapshot.auto_refresh_enabled:
        _refresh_task = asyncio.create_task(
            _periodic_refresh(cfg.snapshot.refresh_interval_hours)
        )
        logger.info("定时刷新已启用: 每 %d 小时", cfg.snapshot.refresh_interval_hours)

    yield

    # Shutdown
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
    await pg_adapter.close_pool()
    await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meridian Atlas",
        version="0.1.0",
        description="Meridian Meta MCP — 元数据中心",
        lifespan=lifespan,
    )

    @app.get("/")
    async def root():
        return {
            "name": "atlas",
            "version": "0.1.0",
            "description": "Meridian Meta MCP — 元数据中心",
            "mcp_sse": "/mcp/sse",
            "mcp_stream": "/mcp/stream",
            "health": "/health",
        }

    app.include_router(health_router)
    app.include_router(services_router, prefix="/api")
    app.include_router(schemas_router, prefix="/api")
    app.include_router(annotations_router, prefix="/api")
    app.include_router(mcp_router, prefix="/mcp")
    app.mount("/mcp/messages/", mcp_sse_messages_app)

    return app


app = create_app()
