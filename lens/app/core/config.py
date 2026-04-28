"""Lens 配置管理 — YAML 驱动，复用 Atlas 模式"""

from pathlib import Path

import yaml
from pydantic import BaseModel


class ServerConfig(BaseModel):
    name: str = "lens"
    environment: str = "dev"
    host: str = "0.0.0.0"
    port: int = 3003
    audit_log_path: str = "./audit.log"


class BusinessMySQLConfig(BaseModel):
    """业务 MySQL 连接配置（向后兼容旧格式）"""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "readonly"
    password: str = ""
    database: list[str] = []


class DatasourceConfig(BaseModel):
    """通用业务数据源配置（支持 mysql / postgresql）"""

    name: str
    type: str = "mysql"  # mysql / postgresql
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "readonly"
    password: str = ""
    database: list[str] | str = []


class MeridianDBConfig(BaseModel):
    """Meridian 平台 PostgreSQL 配置（读写，存储 entity_definition 和查询审计）"""

    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "meridian"
    password: str = "meridian_dev"
    database: str = "meridian"


class QueryConfig(BaseModel):
    """查询约束配置"""

    max_limit: int = 100
    default_limit: int = 20
    default_time_range_days: int = 7
    timeout_seconds: int = 30
    require_filter: bool = True


class Settings(BaseModel):
    server: ServerConfig = ServerConfig()
    business_mysql: BusinessMySQLConfig = BusinessMySQLConfig()  # 向后兼容
    business_datasource: list[DatasourceConfig] = []  # 多数据源（新格式）
    meridian_db: MeridianDBConfig = MeridianDBConfig()
    query: QueryConfig = QueryConfig()
    sensitive_fields: list[str] = [
        "phone",
        "mobile",
        "id_card",
        "identity",
        "password",
        "secret",
        "token",
    ]


_settings: Settings | None = None


def load_settings(config_path: str | None = None) -> Settings:
    global _settings
    if _settings is not None:
        return _settings

    path = Path(config_path or Path(__file__).parent.parent / "settings" / "config.yaml")
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
