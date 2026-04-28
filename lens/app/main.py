"""Lens — HTTP 入口

挂载 HTTP 路由和 MCP 传输层。
启动时初始化数据源连接池，从 PG 加载 entity definitions 到缓存。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters import pg_adapter, registry
from app.adapters.mysql_adapter import MySQLAdapter
from app.api.routes.health import router as health_router
from app.api.routes.entities import router as entities_router
from app.core.config import get_settings
from app.mcp.sse import messages_app as mcp_sse_messages_app
from app.mcp.sse import router as mcp_router

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _register_datasources():
    """根据配置注册业务数据源适配器"""
    settings = get_settings()

    # 多数据源配置（新格式）
    if hasattr(settings, "business_datasource") and settings.business_datasource:
        for ds in settings.business_datasource:
            adapter = _create_adapter(ds)
            if adapter:
                registry.register(ds.name, adapter)
        return

    # 向后兼容：旧的 business_mysql 单数据源配置
    cfg = settings.business_mysql
    if cfg.database:
        adapter = MySQLAdapter(
            adapter_name="default-mysql",
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            databases=cfg.database,
        )
        registry.register("default-mysql", adapter)


def _create_adapter(ds):
    """根据数据源配置创建适配器实例"""
    if ds.type == "mysql":
        return MySQLAdapter(
            adapter_name=ds.name,
            host=ds.host,
            port=ds.port,
            user=ds.user,
            password=ds.password,
            databases=ds.database if isinstance(ds.database, list) else [ds.database],
        )
    elif ds.type == "postgresql":
        # Phase 2 实现
        try:
            from app.adapters.pg_business_adapter import PostgreSQLAdapter
            return PostgreSQLAdapter(
                adapter_name=ds.name,
                host=ds.host,
                port=ds.port,
                user=ds.user,
                password=ds.password,
                database=ds.database if isinstance(ds.database, str) else ds.database[0],
            )
        except ImportError:
            logger.warning("PostgreSQL 业务适配器尚未实现，跳过数据源 '%s'", ds.name)
            return None
    else:
        logger.warning("不支持的数据源类型: %s（数据源: %s）", ds.type, ds.name)
        return None


async def _load_entities():
    """启动后加载 entity definitions（后台执行）"""
    from app.services.entity_service import load_from_pg

    try:
        count = await load_from_pg()
        if count:
            logger.info("启动加载完成: %d 个 entity definition", count)
        else:
            logger.info("尚无 entity definition，等待注册")
    except Exception:
        logger.error("启动加载 entity definitions 失败", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 注册并初始化数据源
    _register_datasources()
    await registry.init_all()
    await pg_adapter.init_pool()

    # 加载 entity definitions
    await _load_entities()

    yield

    # Shutdown
    await pg_adapter.close_pool()
    await registry.close_all()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meridian Lens",
        version="0.1.0",
        description="Meridian 数据查询 MCP — 基于语义层的结构化数据查询",
        lifespan=lifespan,
    )

    @app.get("/")
    async def root():
        return {
            "name": "lens",
            "version": "0.1.0",
            "description": "Meridian 数据查询 MCP — 基于语义层的结构化数据查询",
            "mcp_sse": "/mcp/sse",
            "mcp_stream": "/mcp/stream",
            "health": "/health",
            "datasources": registry.list_adapters(),
        }

    app.include_router(health_router)
    app.include_router(entities_router, prefix="/api")
    app.include_router(mcp_router, prefix="/mcp")
    app.mount("/mcp/messages/", mcp_sse_messages_app)

    return app


app = create_app()
