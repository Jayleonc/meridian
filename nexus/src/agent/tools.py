"""Meridian Agent tool schemas and validation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class ProbeSearchByRequestIdArgs(BaseModel):
    request_id: str = Field(..., description="需要追踪的 request_id。")
    back_hours: int = Field(0, ge=0, le=168, description="向前回溯小时数。0 表示当前小时。")
    hint_time: str | None = Field(None, description="可选时间提示，例如日志发生时间。")


class ProbeSearchLogsArgs(BaseModel):
    keyword: str = Field(..., description="日志关键词。")
    service: str | None = Field(None, description="可选服务名，按日志行开头的服务进程名过滤。")
    start_time: str | None = Field(None, description="可选开始时间。")
    end_time: str | None = Field(None, description="可选结束时间。")
    level: str | None = Field(None, description="可选日志级别，例如 ERR、WAR、INF。")
    limit: int = Field(20, ge=1, le=100, description="最多返回条数。")


class ProbeTailErrorsArgs(BaseModel):
    hours_back: int = Field(1, ge=1, le=168, description="向前查看错误日志的小时数。")
    service: str | None = Field(None, description="可选服务名，限定只看某个服务的错误日志。")
    keyword: str | None = Field(None, description="可选关键词过滤。")
    limit: int = Field(30, ge=1, le=100, description="最多返回条数。")


class ProbeTailServiceLogsArgs(BaseModel):
    service: str = Field(..., description="服务名，来自 probe_list_services 或日志行进程名。")
    hours_back: int = Field(1, ge=1, le=24, description="向前查看服务日志的小时数。")
    level: str | None = Field(None, description="可选日志级别，例如 ERR、WAR、INF。")
    keyword: str | None = Field(None, description="可选关键词过滤。")
    limit: int = Field(50, ge=1, le=100, description="最多返回条数。")
    exclude_noise: bool = Field(False, description="是否隐藏 Register / heartbeat / keepalive 这类普通信息噪音。")


class ProbeListServicesArgs(BaseModel):
    pass


class ProbeContextAroundMatchArgs(BaseModel):
    file: str = Field(..., description="日志文件路径。")
    line_number: int = Field(..., ge=1, description="命中行号。")
    before: int = Field(10, ge=0, le=200, description="向前读取行数。")
    after: int = Field(10, ge=0, le=200, description="向后读取行数。")


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "probe_search_by_request_id": ProbeSearchByRequestIdArgs,
    "probe_search_logs": ProbeSearchLogsArgs,
    "probe_tail_errors": ProbeTailErrorsArgs,
    "probe_tail_service_logs": ProbeTailServiceLogsArgs,
    "probe_list_services": ProbeListServicesArgs,
    "probe_context_around_match": ProbeContextAroundMatchArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "probe_search_by_request_id": "按 request_id 追踪完整日志链路，适合用户提供 request_id 时使用。",
    "probe_search_logs": "按关键词搜索日志，适合查询错误文本、异常类名、业务关键词。",
    "probe_tail_errors": "查看最近错误日志，适合用户询问最近有什么报错或系统是否异常。",
    "probe_tail_service_logs": "按服务名查看最近日志，适合用户想直接查看某个服务的运行日志。",
    "probe_list_services": "列出当前 Probe 可观测到的服务。",
    "probe_context_around_match": "读取日志命中行上下文，适合进一步确认某条日志前后的调用细节。",
}


def available_tool_names() -> list[str]:
    return list(TOOL_ARG_MODELS.keys())


def tool_schemas() -> list[dict[str, Any]]:
    return [_tool_schema(name, model) for name, model in TOOL_ARG_MODELS.items()]


def validate_tool_args(name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    return TOOL_ARG_MODELS[name](**raw_args).model_dump(exclude_none=True)


def compact_tool_result(value: Any, limit: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return {
        "truncated": True,
        "original_chars": len(text),
        "preview": text[:limit],
    }


def _tool_schema(name: str, args_model: type[BaseModel]) -> dict[str, Any]:
    schema = args_model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": schema,
        },
    }
