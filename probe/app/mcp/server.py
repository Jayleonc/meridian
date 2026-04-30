"""
MCP Server 定义

注册所有 Tool 和 Resource，供 AI Agent 调用。
工具设计原则：
  1. 摘要优先 —— search_by_request_id 返回分层摘要而非全量原文，节省 token
  2. 按需深入 —— Agent 看到错误后可调 context_around_match 获取上下文
  3. 清晰引导 —— 每个工具的 docstring 说明「什么时候该用」和「下一步该做什么」
"""

import json

from mcp.server.fastmcp import FastMCP

from app.services import log_service

mcp = FastMCP("probe")


def _with_token_stats(json_str: str) -> str:
    """给返回的 JSON 注入 token 用量估算，方便观察每次查询的开销。

    估算规则（Claude tokenizer 近似）：
    - 中文：约 1 token / 1.5 字符
    - 英文/代码：约 1 token / 4 字符
    - 混合文本取中间值：字符数 / 2.5
    """
    char_count = len(json_str)
    estimated_tokens = int(char_count / 2.5)

    data = json.loads(json_str)
    data["_token_stats"] = {
        "response_chars": char_count,
        "estimated_tokens": estimated_tokens,
    }
    return json.dumps(data, ensure_ascii=False)


# ============================================================
# Tools —— AI Agent 可调用的排障工具
# ============================================================

@mcp.tool(name="search_by_request_id")
async def search_by_request_id(
    request_id: str,
    back_hours: int = 0,
    hint_time: str | None = None,
    include_full: bool = False,
) -> str:
    """【最常用】根据请求ID追踪完整链路。

    Args:
        request_id: 请求ID，如 '7n8dpbl2SRiZmnpytX4A' 或 'SnWCax0iwhiYZPO4RNsA.NWtYBR'
        back_hours: 往前搜索的小时数。0=仅当前小时，有 hint_time 时忽略此参数
        hint_time: 用户提到的请求时间，如 '17:12:40'、'03-18T17:12'，服务端自动计算 back_hours
        include_full: 是否附带 glog.sh / 文件搜索返回的完整原始日志行
    """
    result = await log_service.search_by_request_id(request_id, back_hours, hint_time, include_full)
    return _with_token_stats(json.dumps(result.model_dump(), ensure_ascii=False))


@mcp.tool(name="search_logs")
async def search_logs(
    keyword: str,
    service: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    level: str | None = None,
    limit: int = 20,
) -> str:
    """按关键词搜索日志。适用于：不知道 request_id 时按报错信息/服务名模糊查找。

    建议：如果已有 request_id，优先用 search_by_request_id，效率更高。

    Args:
        keyword: 搜索关键词（服务名、错误信息、接口路径等）
        service: 可选服务名，按日志行开头的服务进程名过滤
        start_time: 开始时间 ISO格式如 '2026-03-18T15:00:00'，默认最近1小时
        end_time: 结束时间 ISO格式，默认当前时间
        level: 日志级别 (INF/WAR/ERR/DBG)，不填则全部
        limit: 最大返回条数，默认20，上限500
    """
    result = await log_service.search_logs(keyword, start_time, end_time, level, limit, service=service)
    return _with_token_stats(json.dumps(result.model_dump(), ensure_ascii=False))


@mcp.tool(name="search_ops_logs")
async def search_ops_logs(
    service: str,
    keyword: str,
    hosts: list[str],
    hours_back: int = 1,
    limit: int = 50,
) -> str:
    """通过 ops 聚合接口跨多台业务服务器搜索日志。

    当前是 anlog.sh 生产适配前的预备接口。默认禁用；启用后仅允许配置白名单
    host，并返回可表达 partial success 的结构化结果。

    Args:
        service: 服务名
        keyword: 搜索关键词
        hosts: 要查询的 host 列表，必须在 Probe ops 配置白名单内
        hours_back: 往前查多少小时，默认1
        limit: 最大返回条数，默认50，上限随 Probe limits.max_lines
    """
    result = await log_service.search_ops_logs(service, keyword, hours_back, hosts, limit)
    return _with_token_stats(json.dumps(result.model_dump(), ensure_ascii=False))


@mcp.tool(name="tail_errors")
async def tail_errors(
    hours_back: int = 1,
    service: str | None = None,
    keyword: str | None = None,
    limit: int = 30,
) -> str:
    """快速巡检：查看最近 N 小时的 ERR 级别日志。适用于回答「系统现在有没有报错」。

    发现感兴趣的错误后，用 search_by_request_id 追踪完整链路。

    Args:
        hours_back: 往前查多少小时，默认1
        service: 可选服务名，限定只看某个服务的错误日志
        keyword: 额外过滤词（如 'timeout'、'hlopen'），不填则看全部 ERR
        limit: 最大返回条数，默认30，上限500
    """
    result = await log_service.tail_errors(hours_back, keyword, limit, service=service)
    return _with_token_stats(json.dumps(result.model_dump(), ensure_ascii=False))


@mcp.tool(name="tail_service_logs")
async def tail_service_logs(
    service: str,
    hours_back: int = 1,
    level: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    exclude_noise: bool = False,
) -> str:
    """按服务查看最近日志。适用于：用户想直接看某个服务的日志。

    Args:
        service: 服务名，来自 list_services 或日志行进程名
        hours_back: 往前查多少小时，默认1
        level: 可选日志级别 (INF/WAR/ERR/DBG)
        keyword: 可选关键词过滤
        limit: 最大返回条数，默认50，上限500
        exclude_noise: 是否隐藏 Register / heartbeat / keepalive 这类普通信息噪音
    """
    result = await log_service.tail_service_logs(service, hours_back, level, keyword, limit, exclude_noise=exclude_noise)
    return _with_token_stats(json.dumps(result.model_dump(), ensure_ascii=False))


@mcp.tool(name="list_services")
async def list_services() -> str:
    """列出当前环境中所有已知的服务。优先从 Atlas 获取，Atlas 不可用时降级到本地发现。"""
    result = await log_service.get_services()
    return _with_token_stats(json.dumps(result, ensure_ascii=False))


@mcp.tool(name="context_around_match")
async def context_around_match(
    file: str,
    line_number: int,
    before: int = 10,
    after: int = 10,
) -> str:
    """查看某条日志前后的上下文。当你需要了解一条错误的前因后果时使用。

    file 和 line_number 参数来自 search_logs / tail_errors 的返回结果。

    Args:
        file: 日志文件路径（从搜索结果中获取）
        line_number: 行号（从搜索结果中获取）
        before: 向前取多少行，默认10，上限50
        after: 向后取多少行，默认10，上限50
    """
    result = log_service.get_context(file, line_number, before, after)
    return _with_token_stats(json.dumps(result, ensure_ascii=False))


# ============================================================
# Resources —— 静态上下文，Agent 可按需读取
# ============================================================

@mcp.resource("probe://guide/troubleshooting")
def troubleshooting_guide() -> str:
    """排障指南：介绍系统架构和常见排障流程"""
    return """# Probe 排障指南

## 系统架构
请求链路: 客户端 → revproxy(反向代理) → 业务服务(jzweg/jzadapter/wwrpabase等) → smq(消息队列) → 下游消费者

## 日志级别
- ERR: 错误，需要关注
- WAR: 警告，可能需要关注（如重试）
- INF: 正常信息
- DBG: 调试信息

## 常见排障流程
1. 拿到 request_id → 用 search_by_request_id 查链路摘要
2. 看 errors 列表 → 定位哪个服务报错
3. 如果是 smq 消费失败 → 关注 retry 信息，看是否有下游服务不可用
4. 常见错误码: -21 = HTTP 404（接口不存在）, -22 = 超时

## 服务说明
- revproxy: 反向代理，所有请求入口
- jzweg: 渠道网关，处理第三方回调
- jzadapter: 适配器，做数据转换和分发
- smq: 消息队列，异步分发事件
- wwrpabase: 基础数据服务（机器人、群等）
- dbproxy: 数据库代理，所有 SQL 经过这里
- hlopen: 开放平台服务
"""


@mcp.resource("probe://guide/log-format")
def log_format_guide() -> str:
    """日志格式说明"""
    return """# Brick 微服务日志格式

## 单行格式
服务名(pid,tid) MM-DDThh:mm:ss.ssss <request_id> LEVEL source message

## 字段说明
- 服务名: 产生日志的微服务进程名
- request_id: 请求追踪 ID，同一请求链路共享前缀，子链路用 . 分隔（如 NRVBpY12SRid6uIz4k4A.SCHuBQ）
- LEVEL: INF / WAR / ERR / DBG
- source: 代码文件:行号:函数名

## RPC 日志格式（rpc.go 产生的）
ctx {req_id},{client_ip},{path},{caller},{server_ip},{hop},{corp_id},{app_id} path {rpc_path} code {code} req {...} rsp {...} time {ms}
- code 0 = 成功
- code 非 0 = 错误
"""
