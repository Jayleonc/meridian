"""
数据模型定义

定义日志查询返回的结构化数据模型。
"""

from pydantic import BaseModel


class LogItem(BaseModel):
    """单条日志"""
    timestamp: str
    level: str
    request_id: str | None = None
    source: str = ""           # 来源 file:line:func
    text: str                  # 日志正文（已截断）
    file: str = ""             # 日志文件路径
    line_number: int = 0


class SearchResult(BaseModel):
    """通用搜索结果"""
    query: dict
    summary: dict
    items: list[LogItem]
    next_actions: list[str] = []


class TraceItem(BaseModel):
    """链路中的单个节点（精简版，省 token）"""
    timestamp: str
    level: str
    service: str               # 服务名（从进程名提取）
    source: str                # 代码位置
    message: str               # 精简消息（已截断）
    request_id: str | None = None


class TraceSummary(BaseModel):
    """请求链路的摘要视图 —— 让 Agent 快速了解全貌，无需读完所有日志"""
    request_id: str
    total_lines: int           # 原始日志总行数
    time_range: str            # 搜到的日志时间范围，如 "12:12:52 ~ 12:12:55"
    searched_hours: int        # 本次搜索的 back_hours 参数值
    services: list[str]        # 经过的服务列表（去重有序）
    error_count: int
    warn_count: int
    errors: list[TraceItem]    # 所有 ERR 日志（完整保留）
    warns: list[TraceItem]     # 所有 WAR 日志（完整保留）
    timeline: list[TraceItem]  # 全链路精简时间线（INF/DBG 级别）
    hint: str = ""             # 给 Agent 的智能提示（如结果可能不完整时提醒扩大搜索）
    next_actions: list[str] = []
