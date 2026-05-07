"""Meridian Agent tool schemas and validation."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProbeSearchByRequestIdArgs(BaseModel):
    request_id: str = Field(..., description="需要追踪的 request_id。")
    back_hours: int = Field(0, ge=0, le=168, description="向前回溯小时数。0 表示当前小时。")
    hint_time: str | None = Field(None, description="可选时间提示，例如日志发生时间。")
    include_full: bool = Field(False, description="是否返回 glog.sh / 文件搜索的完整原始日志行。用户要求具体查看或完整日志时设为 true。")


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


class ProbeSearchOpsLogsArgs(BaseModel):
    service: str = Field(..., min_length=1, description="服务名。")
    keyword: str = Field(..., min_length=1, description="日志关键词。")
    hosts: list[str] = Field(..., min_length=1, description="要查询的业务主机列表，必须在 Probe ops 白名单内。")
    hours_back: int = Field(1, ge=1, le=24, description="向前查看小时数。")
    limit: int = Field(50, ge=1, le=100, description="最多返回条数。")


class MeridianDiagnoseRequestArgs(BaseModel):
    request_id: str = Field(..., min_length=1, description="需要诊断的 request_id。")
    back_hours: int = Field(0, ge=0, le=72, description="向前回溯小时数。0 表示当前小时。")
    hint_time: str | None = Field(None, description="可选日志时间提示。")
    include_full: bool = Field(False, description="是否让 Probe 返回完整原始日志行。默认 false。")
    include_lens_counts: bool = Field(True, description="是否对候选 Lens 实体执行 count。")
    max_entities: int = Field(3, ge=0, le=5, description="最多尝试的 Lens 候选实体数量。")


class AtlasListServicesArgs(BaseModel):
    pass


class AtlasSearchMetaArgs(BaseModel):
    query: str = Field(..., min_length=1, description="元数据搜索关键词，例如服务名、表名、字段名或业务语义。")


class AtlasGetTableArgs(BaseModel):
    database: str = Field(..., min_length=1, description="数据库名。")
    table: str = Field(..., min_length=1, description="表名。")


class LensListEntitiesArgs(BaseModel):
    pass


class LensDescribeEntityArgs(BaseModel):
    entity: str = Field(..., min_length=1, description="业务实体名称，来自 lens_list_entities。")


class LensFilterConditionArgs(BaseModel):
    field: str = Field(..., min_length=1, description="业务实体字段名。")
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "like", "between"] = Field(
        "eq",
        description="筛选操作符。",
    )
    value: Any = Field(None, description="筛选值；in/between 可传数组。")


class LensTimeRangeArgs(BaseModel):
    start: str | None = Field(None, description="开始时间或日期。")
    end: str | None = Field(None, description="结束时间或日期。")


class LensQueryArgs(BaseModel):
    entity: str = Field(..., min_length=1, description="业务实体名称。")
    filter: list[LensFilterConditionArgs] = Field(
        default_factory=list,
        description="筛选条件列表；仍由 Lens 后端校验是否合法。",
    )
    field: list[str] | None = Field(None, description="要返回的字段；为空时使用实体默认字段。")
    aggregate: Literal["count"] | None = Field(None, description='聚合模式；当前仅支持 "count"。')
    preview: bool = Field(False, description="受限样本预览模式；只返回默认安全字段，不能代替全量查询。")
    order_by: str | None = Field(None, description='排序字段；前缀 "-" 表示降序。')
    limit: int = Field(20, ge=1, le=100, description="明细返回条数，最大 100。")
    time_range: LensTimeRangeArgs | None = Field(None, description="时间范围约束。")


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "probe_search_by_request_id": ProbeSearchByRequestIdArgs,
    "probe_search_logs": ProbeSearchLogsArgs,
    "probe_tail_errors": ProbeTailErrorsArgs,
    "probe_tail_service_logs": ProbeTailServiceLogsArgs,
    "probe_list_services": ProbeListServicesArgs,
    "probe_context_around_match": ProbeContextAroundMatchArgs,
    "probe_search_ops_logs": ProbeSearchOpsLogsArgs,
    "meridian_diagnose_request": MeridianDiagnoseRequestArgs,
    "atlas_list_services": AtlasListServicesArgs,
    "atlas_search_meta": AtlasSearchMetaArgs,
    "atlas_get_table": AtlasGetTableArgs,
    "lens_list_entities": LensListEntitiesArgs,
    "lens_describe_entity": LensDescribeEntityArgs,
    "lens_query": LensQueryArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "probe_search_by_request_id": "按 request_id 追踪完整日志链路，适合用户提供 request_id 时使用；用户要求具体查看或完整日志时设置 include_full=true。",
    "probe_search_logs": "按关键词搜索日志，适合查询错误文本、异常类名、业务关键词。",
    "probe_tail_errors": "查看最近错误日志，适合用户询问最近有什么报错或系统是否异常。",
    "probe_tail_service_logs": "按服务名查看最近日志，适合用户想直接查看某个服务的运行日志。",
    "probe_list_services": "列出当前 Probe 可观测到的服务。",
    "probe_context_around_match": "读取日志命中行上下文，适合进一步确认某条日志前后的调用细节。",
    "probe_search_ops_logs": "通过 Probe ops 聚合接口跨多台业务主机搜索服务日志；当前默认禁用，启用后只允许白名单 host。",
    "meridian_diagnose_request": "按 request_id 自动收集 Probe 链路、Atlas 元数据和 Lens 候选实体 count，返回一包可用于排障的结构化证据。",
    "atlas_list_services": "通过 Atlas 列出业务服务元数据，用于回答当前有哪些服务、状态和部署/日志线索。",
    "atlas_search_meta": "通过 Atlas 按关键词搜索元数据，用于查找相关服务、表、字段和语义标注。",
    "atlas_get_table": "通过 Atlas 获取指定表详情，用于查看字段结构、注释、语义和近似行数。",
    "lens_list_entities": "通过 Lens 列出可查询业务实体，用于决定后续业务数据查询入口。",
    "lens_describe_entity": "通过 Lens 查看业务实体字段、语义和查询约束，查询前应先调用。",
    "lens_query": "通过 Lens DSL 执行业务数据只读查询，支持 count 和明细；不要生成 SQL，DSL 仍由 Lens 后端校验。",
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
