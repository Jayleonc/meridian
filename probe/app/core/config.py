"""
配置管理

从 config.yaml 加载配置，支持默认值。
"""

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LimitsConfig(BaseModel):
    max_lines: int = 50                    # search_logs / tail_errors 的最大返回行数
    max_bytes: int = 65536                 # 预留：单次返回的最大字节数
    max_time_range_hours: int = 24         # 搜索时间范围上限（小时）
    command_timeout_seconds: int = 10      # 外部命令（glog.sh / grep）超时秒数
    max_line_length: int = 500             # 单行日志最大长度，超出截断


class SecurityConfig(BaseModel):
    redact_enabled: bool = True            # 是否开启敏感信息脱敏


class PathsConfig(BaseModel):
    hourly_log_dir: str = "/data/brick/log"                   # 小时级日志目录
    supervisor_log_dir: str = "/var/log/supervisor"            # supervisor 日志目录
    glog_path: str = "/data/pinfire/tools/glog.sh"            # glog.sh 路径


class TimeConfig(BaseModel):
    log_timezone: str = "Asia/Shanghai"       # 小时日志文件名使用的业务日志时区


class ServerConfig(BaseModel):
    name: str = "probe"
    environment: str = "dev"
    host: str = "0.0.0.0"
    port: int = 3002
    audit_log_path: str = "./audit.log"    # 审计日志路径


class AtlasConfig(BaseModel):
    """Atlas 连接配置（用于获取服务列表等元数据）"""

    url: str = "http://127.0.0.1:3001"  # Atlas HTTP 地址
    timeout: int = 5  # 请求超时（秒）


class Settings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    time: TimeConfig = Field(default_factory=TimeConfig)
    atlas: AtlasConfig = Field(default_factory=AtlasConfig)


def load_settings(config_path: str | Path | None = None) -> Settings:
    """加载配置文件，找不到则用默认值"""
    if config_path is None:
        config_path = (
            os.environ.get("MERIDIAN_PROBE_CONFIG")
            or Path(__file__).parent.parent / "settings" / "config.yaml"
        )

    config_path = Path(config_path)
    if not config_path.exists():
        print(f"警告: 未找到配置文件 {config_path}，使用默认配置", file=sys.stderr)
        return Settings()

    with open(config_path) as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return Settings(**data)


settings = load_settings()
