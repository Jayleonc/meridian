"""Atlas 配置管理 — 复用 Probe 的 YAML 驱动模式"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class ServerConfig(BaseModel):
    name: str = "atlas"
    environment: str = "dev"
    host: str = "0.0.0.0"
    port: int = 3001
    audit_log_path: str = "./audit.log"


class BusinessMySQLConfig(BaseModel):
    """业务 MySQL 连接配置（只读，用于采集 information_schema）"""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "readonly"
    password: str = ""
    database: list[str] = []  # 要采集的业务数据库列表


class MeridianDBConfig(BaseModel):
    """Meridian 平台 PostgreSQL 配置（读写，存储元数据快照、语义标注等）"""

    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "meridian"
    password: str = "meridian_dev"
    database: str = "meridian"


class SupervisorConfig(BaseModel):
    """Supervisor 连接配置（用于采集服务列表）"""

    enabled: bool = False
    xmlrpc_url: str = "http://127.0.0.1:9001/RPC2"
    log_dir: str = "/var/log/supervisor"


class ProbeLogDiscoveryConfig(BaseModel):
    """Probe 日志服务发现配置（兜底来源）"""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:3002"
    timeout_seconds: int = 5


class StaticServiceConfig(BaseModel):
    """静态服务声明（本地开发 / 手动注册）"""

    name: str
    status: str = "RUNNING"
    source: str = ""
    deploy_path: str = ""
    log_path: str = ""
    database_list: list[str] = []


class ServiceDiscoveryConfig(BaseModel):
    """服务发现配置"""

    providers: list[str] = ["supervisor", "static"]  # 按优先级排序
    static_services: list[StaticServiceConfig] = []


class SnapshotConfig(BaseModel):
    """快照与 diff 配置"""

    collect_on_startup: bool = False
    auto_refresh_enabled: bool = False
    refresh_interval_hours: int = 24


class LimitsConfig(BaseModel):
    max_tables: int = 500
    max_columns_per_table: int = 200
    search_result_limit: int = 50


class Settings(BaseModel):
    server: ServerConfig = ServerConfig()
    business_mysql: BusinessMySQLConfig = BusinessMySQLConfig()
    meridian_db: MeridianDBConfig = MeridianDBConfig()
    supervisor: SupervisorConfig = SupervisorConfig()
    probe_logs: ProbeLogDiscoveryConfig = ProbeLogDiscoveryConfig()
    discovery: ServiceDiscoveryConfig = ServiceDiscoveryConfig()
    snapshot: SnapshotConfig = SnapshotConfig()
    limits: LimitsConfig = LimitsConfig()


_settings: Settings | None = None


def load_settings(config_path: str | None = None) -> Settings:
    global _settings
    if _settings is not None:
        return _settings

    path = Path(
        config_path
        or os.environ.get("MERIDIAN_ATLAS_CONFIG", "")
        or Path(__file__).parent.parent / "settings" / "config.yaml"
    )
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _settings = Settings(**data)
    else:
        _settings = Settings()

    return _settings


def get_settings() -> Settings:
    if _settings is None:
        return load_settings()
    return _settings
