"""
日志查询业务逻辑

提供按 request_id 追踪、关键词搜索、错误巡检等核心功能。
"""

import json
import re
import sys
from datetime import datetime, timedelta

from app.adapters import file_adapter, glog_adapter
from app.core.config import settings
from app.schemas.probe import LogItem, SearchResult, TraceItem, TraceSummary
from app.utils.log_parser import parse_log_line, _clean_ansi, _truncate, _strip_rpc_body
from app.utils.redact import redact_text


def _maybe_redact(text: str) -> str:
    """按配置决定是否脱敏"""
    text = _clean_ansi(text)
    if settings.security.redact_enabled:
        return redact_text(text)
    return text


def _audit(tool: str, params: dict, result_count: int, truncated: bool, error: str = ""):
    """写审计日志"""
    entry = {
        "time": datetime.now().isoformat(),
        "tool": tool,
        "params": params,
        "result_count": result_count,
        "truncated": truncated,
        "error": error,
    }
    try:
        with open(settings.server.audit_log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"审计日志写入失败: {e}", file=sys.stderr)


def _raw_lines_to_items(
    lines: list[str],
    file: str = "",
    line_numbers: list[int] | None = None,
    *,
    include_full: bool = False,
) -> list[LogItem]:
    """将原始日志行批量转为 LogItem"""
    items = []
    for i, line in enumerate(lines):
        parsed = parse_log_line(line, max_message_length=None if include_full else 0)
        ln = line_numbers[i] if line_numbers and i < len(line_numbers) else 0
        if parsed:
            items.append(LogItem(
                timestamp=parsed["timestamp"],
                level=parsed["level"],
                service=parsed["process"],
                request_id=parsed["request_id"],
                source=parsed["source"],
                text=_maybe_redact(parsed["message"]),
                file=file,
                line_number=ln,
            ))
        else:
            items.append(LogItem(
                timestamp="",
                level="",
                text=_maybe_redact(line.strip() if include_full else _truncate(line.strip())),
                file=file,
                line_number=ln,
            ))
    return items


def _grep_results_to_items(
    results: list[tuple[str, int, str]],
    *,
    include_full: bool = False,
) -> list[LogItem]:
    """将 grep 结果转为 LogItem 列表"""
    items = []
    for filename, line_num, text in results:
        parsed = parse_log_line(text, max_message_length=None if include_full else 0)
        if parsed:
            items.append(LogItem(
                timestamp=parsed["timestamp"],
                level=parsed["level"],
                service=parsed["process"],
                request_id=parsed["request_id"],
                source=parsed["source"],
                text=_maybe_redact(parsed["message"]),
                file=filename,
                line_number=line_num,
            ))
        else:
            items.append(LogItem(
                timestamp="",
                level="",
                text=_maybe_redact(text.strip() if include_full else _truncate(text.strip())),
                file=filename,
                line_number=line_num,
            ))
    return items


def _items_time_range(items: list[LogItem]) -> dict[str, str]:
    timestamps = [item.timestamp for item in items if item.timestamp]
    if not timestamps:
        return {"start": "", "end": ""}
    return {"start": timestamps[0], "end": timestamps[-1]}


def _tail_summary(items: list[LogItem], limit: int, truncated: bool, files: list) -> dict:
    """构造 tail 类接口的摘要，并显式暴露“最新命中是否陈旧”。

    tail_service_logs 返回的是指定窗口里的最近匹配，不代表服务当前仍有日志。
    对值班排障来说，最新命中距今多久和扫描了哪些小时文件同样关键。
    """
    now = datetime.now(file_adapter._log_timezone())
    summary = {
        "total_matches": len(items),
        "returned": len(items),
        "limit": limit,
        "truncated": truncated,
        "time_range": _items_time_range(items),
        "log_now": now.isoformat(),
        "files_scanned": [str(file) for file in files],
    }
    if not items:
        summary["stale"] = True
        summary["hint"] = "当前时间窗口内没有匹配日志；这通常表示服务无新日志或服务名/过滤条件不匹配。"
        return summary

    latest = _parse_log_timestamp(items[-1].timestamp, now)
    if latest is None:
        return summary
    age_seconds = max(0, int((now.replace(tzinfo=None) - latest).total_seconds()))
    summary["latest_age_seconds"] = age_seconds
    summary["stale"] = age_seconds > 300
    if summary["stale"]:
        summary["hint"] = f"最新匹配日志距当前约 {age_seconds} 秒；返回的是窗口内最后一次命中，不代表服务当前仍在产生日志。"
    return summary


def _parse_log_timestamp(timestamp: str, reference: datetime) -> datetime | None:
    if not timestamp:
        return None
    for fmt in ("%m-%dT%H:%M:%S.%f", "%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(timestamp, fmt)
            return parsed.replace(year=reference.year)
        except ValueError:
            continue
    return None


def _service_log_pattern(
    service: str,
    *,
    level: str | None = None,
    keyword: str | None = None,
) -> str:
    """构造按服务过滤的日志正则。

    Brick 日志行以 `service(pid,tid)` 开头，服务过滤必须锚定行首，避免普通 keyword
    命中请求体或错误文本里的同名字符串。
    """
    parts = [rf"^{re.escape(service)}\("]
    if level and keyword:
        level_token = _level_grep_token(level)
        escaped_keyword = re.escape(keyword)
        parts.append(rf".*({level_token}.*{escaped_keyword}|{escaped_keyword}.*{level_token})")
    elif level:
        parts.append(rf".*{_level_grep_token(level)}")
    elif keyword:
        parts.append(rf".*{re.escape(keyword)}")
    return "".join(parts)


def _level_grep_token(level: str) -> str:
    """返回适合 grep -E 的级别字段候选。

    不用 `\bERR\b`，因为不同 grep 实现对 `\b` 支持不一致；同时 `ERR`
    可能出现在 request_id 或正文里。Brick level 后面固定跟空白和 source。
    """
    return rf"{re.escape(level.upper())}[[:space:]]+"


def _level_keyword_pattern(level: str, keyword: str | None = None) -> str:
    token = _level_grep_token(level)
    if not keyword:
        return token
    escaped = re.escape(keyword)
    return rf"{token}.*{escaped}|{escaped}.*{token}"


def _normalize_level(level: str | None) -> str | None:
    if not level:
        return None
    normalized = level.strip().upper()
    return normalized if normalized in {"ERR", "WAR", "INF", "DBG", "IMP"} else normalized


def _is_noise_log(item: LogItem) -> bool:
    """识别服务日志里的低价值注册/心跳噪音。

    错误和告警永远保留；只隐藏普通信息日志中的 Register / heartbeat / keepalive。
    """
    if item.level in {"ERR", "WAR", "IMP"}:
        return False
    haystack = f"{item.source} {item.text}".lower()
    return any(token in haystack for token in ("register", "registry", "heartbeat", "keepalive"))


def _filter_items(
    items: list[LogItem],
    *,
    service: str | None = None,
    level: str | None = None,
    exclude_noise: bool = False,
) -> list[LogItem]:
    normalized_level = _normalize_level(level)
    filtered = items
    if service:
        filtered = [item for item in filtered if item.service == service]
    if normalized_level:
        filtered = [item for item in filtered if item.level == normalized_level]
    if exclude_noise:
        filtered = [item for item in filtered if not _is_noise_log(item)]
    return filtered


def _tail_scan_limit(limit: int, *, has_app_filter: bool = False) -> int:
    if not has_app_filter:
        return limit
    return min(max(limit * 5, limit), 2500)


def _parsed_to_trace_item(parsed: dict, compact_max: int = 0) -> TraceItem:
    """将 parse_log_line 的结果转为精简的 TraceItem。

    compact_max > 0 时对 message 做压缩：
    - 去掉 RPC 日志中的 req/rsp body（只留占位符）
    - 截断到 compact_max 字符
    """
    msg = parsed["message"]
    if compact_max > 0:
        msg = _strip_rpc_body(msg)
        msg = _truncate(msg, max_len=compact_max)
    return TraceItem(
        timestamp=parsed["timestamp"],
        level=parsed["level"],
        service=parsed["process"],
        source=parsed["source"],
        message=_maybe_redact(msg),
        request_id=parsed["request_id"],
    )


def _calc_back_hours(hint_time: str) -> int:
    """
    根据用户提供的时间字符串计算 back_hours。

    支持格式：
    - "17:12:40" / "17:12" — 今天的某个时间
    - "2026-03-18T17:12:40" / "2026-03-18 17:12:40" — 完整时间
    - "03-18T17:12:40" — 日志格式的时间

    返回：向前搜索的小时数（向上取整，+1 小时缓冲）
    """
    now = datetime.now()
    hint = hint_time.strip()

    target: datetime | None = None

    # 尝试各种格式
    for fmt in (
        "%H:%M:%S", "%H:%M",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
        "%m-%dT%H:%M:%S", "%m-%dT%H:%M",
    ):
        try:
            parsed = datetime.strptime(hint, fmt)
            # 补全缺失的日期/年份
            target = parsed.replace(
                year=now.year if parsed.year == 1900 else parsed.year,
                month=now.month if fmt.startswith("%H") else parsed.month,
                day=now.day if fmt.startswith("%H") else parsed.day,
            )
            break
        except ValueError:
            continue

    if target is None:
        return 0  # 解析失败，用默认值

    diff_hours = (now - target).total_seconds() / 3600
    if diff_hours < 0:
        # 用户说的时间在未来？可能是昨天的同一时间
        target = target - timedelta(days=1)
        diff_hours = (now - target).total_seconds() / 3600

    # 向上取整 + 1 小时缓冲，最少 1
    return max(1, int(diff_hours) + 1)


async def search_by_request_id(
    request_id: str,
    back_hours: int = 0,
    hint_time: str | None = None,
    include_full: bool = False,
) -> TraceSummary:
    """
    按 request_id 搜索完整请求链路。

    返回结构化摘要：
    - errors/warns: 完整保留，Agent 第一时间看到问题
    - timeline: 全链路精简时间线，快速了解流转过程
    - services: 经过的服务列表
    - time_range: 搜到的日志时间范围（帮助判断是否找对了）
    - hint: 当结果可能不完整时给出提示
    """
    # 如果用户提供了时间提示，自动计算 back_hours
    if hint_time:
        back_hours = _calc_back_hours(hint_time)

    params = {
        "request_id": request_id,
        "back_hours": back_hours,
        "hint_time": hint_time,
        "include_full": include_full,
    }
    try:
        raw = await glog_adapter.glog_search(request_id, back_hours)
        lines = [line for line in raw.splitlines() if line.strip()]
        source = "glog"
        if not lines:
            lines = await _search_request_id_from_files(request_id, back_hours, include_full=include_full)
            source = "hourly_log_file_fallback"
        total = len(lines)
        raw_lines = [_maybe_redact(line) for line in lines] if include_full else []

        # 分类：错误 / 警告 / 普通
        errors: list[TraceItem] = []
        warns: list[TraceItem] = []
        timeline: list[TraceItem] = []
        services_seen: list[str] = []  # 保持顺序的去重列表
        timestamps: list[str] = []     # 收集所有时间戳，用于计算时间范围

        for line in lines:
            parsed = parse_log_line(line)
            if not parsed:
                continue

            timestamps.append(parsed["timestamp"])

            # 记录服务出现顺序
            svc = parsed["process"]
            if svc not in services_seen:
                services_seen.append(svc)

            if parsed["level"] in ("ERR", "IMP"):
                # IMP = Important，比 ERR 更严重（如 final fail / message drop）
                errors.append(_parsed_to_trace_item(parsed, compact_max=300))
            elif parsed["level"] == "WAR":
                warns.append(_parsed_to_trace_item(parsed, compact_max=300))
            else:
                # timeline：去掉 req/rsp body，截断到 150 字符
                timeline.append(_parsed_to_trace_item(parsed, compact_max=150))

        # 计算时间范围
        if timestamps:
            time_range = f"{timestamps[0]} ~ {timestamps[-1]}"
        else:
            time_range = "无"

        # 限制 timeline 条数，保留头尾各 15 条，中间省略
        max_timeline = 30
        if len(timeline) > max_timeline:
            half = max_timeline // 2
            omitted = len(timeline) - max_timeline
            head = timeline[:half]
            tail = timeline[-half:]
            timeline = head + [TraceItem(
                timestamp="", level="INF", service="---",
                source="", message=f"[省略中间 {omitted} 条 INF/DBG 日志]",
            )] + tail

        # 生成智能提示：帮助 Agent 判断是否需要扩大搜索
        hint = _build_search_hint(total, back_hours, services_seen, errors, time_range)
        if source != "glog":
            hint = (
                f"[已自动降级] glog.sh 未返回结果，已改用小时日志文件搜索 request_id。"
                f"{hint}"
            )

        _audit("search_by_request_id", params, total, False)
        return TraceSummary(
            request_id=request_id,
            total_lines=total,
            time_range=time_range,
            searched_hours=back_hours,
            services=services_seen,
            error_count=len(errors),
            warn_count=len(warns),
            errors=errors,
            warns=warns,
            timeline=timeline,
            raw_lines=raw_lines,
            hint=hint,
            next_actions=["search_logs", "context_around_match", "search_by_request_id_include_full"],
        )
    except Exception as e:
        _audit("search_by_request_id", params, 0, False, str(e))
        raise


async def _search_request_id_from_files(
    request_id: str,
    back_hours: int,
    *,
    include_full: bool = False,
) -> list[str]:
    """当 glog.sh 查不到时，退回到 Probe 本机小时日志文件搜索。

    search_logs 本来就能搜到这类日志；这里把同样的文件证据接入 request_id
    链路摘要，避免 Agent 被单一 adapter 的空结果误导。
    """
    if back_hours > 0:
        files = file_adapter.get_recent_hourly_files(back_hours)
    else:
        now = datetime.now()
        files = file_adapter.get_hourly_files(now.replace(minute=0, second=0, microsecond=0), now)
    results = await file_adapter.grep_files(
        files,
        request_id,
        settings.limits.max_lines,
        include_full_lines=include_full,
    )
    return [line for _, _, line in results]


def _build_search_hint(
    total: int, back_hours: int, services: list[str], errors: list, time_range: str,
) -> str:
    """
    根据搜索结果生成智能提示，引导 Agent 做出正确决策。

    典型的完整链路通常包含 20+ 行、3+ 个服务。
    如果结果太少，很可能搜索范围不够，或者搜到了不相关的同名请求。
    """
    hints: list[str] = []

    if total == 0:
        hints.append(
            f"[需要用户确认] 未找到任何日志（back_hours={back_hours}）。"
            "请询问用户这个请求大概发生在什么时间，然后用对应的 back_hours 重新搜索。"
        )

    elif back_hours == 0:
        # 默认时间范围只搜当前小时，可能搜到同名但时间不对的请求
        # 必须先告诉用户找到的时间，让用户确认再分析
        hints.append(
            f"[先确认时间] 找到日志，时间在 {time_range}。"
            "在分析之前，请先告诉用户这个时间范围，确认是否是他要找的那次请求。"
            "如果时间不对，根据用户说的时间调整 back_hours 重搜。"
        )

    elif total < 10 and len(services) <= 2:
        hints.append(
            f"[结果可能不完整] 仅找到 {total} 行、{len(services)} 个服务，时间在 {time_range}。"
            "先告诉用户找到的时间范围，确认是否正确。"
        )

    if errors:
        # 检测消息最终被丢弃（最严重的结果）
        dropped_topics = []
        for e in errors:
            msg = e.message
            if "touch max retry count, drop" in msg or "final fail" in msg:
                # 提取 topic 名（如 jzadapter_event_cb.hlopen_contact_apply）
                # 格式：consumeMsg <topic>: msg ... / final fail: <topic>: ...
                m = re.search(r'(?:consumeMsg|final fail:)\s+([\w.]+)', msg)
                topic = m.group(1) if m else "unknown"
                dropped_topics.append(topic)

        if dropped_topics:
            hints.append(
                f"[消息丢弃] 以下消息队列的消息已达到最大重试次数并被丢弃: {', '.join(set(dropped_topics))}。"
                "这是本次请求最严重的问题，优先分析这些 ERR，其他 ERR 可能只是中间步骤的日志，不是根因。"
            )
        else:
            # 检测 404 错误涉及的服务
            error_services = set()
            for e in errors:
                if "404" in e.message or "Http 404" in e.message:
                    for keyword in ["hlopen", "hlfront", "wwrpabase", "jzadapter"]:
                        if keyword in e.message:
                            error_services.add(keyword)
            if error_services:
                hints.append(
                    f"发现 HTTP 404 错误，涉及服务: {', '.join(error_services)}。"
                    "这些服务的接口可能未注册或服务未部署。"
                )

    return " ".join(hints)


async def search_logs(
    keyword: str,
    start_time: str | None = None,
    end_time: str | None = None,
    level: str | None = None,
    limit: int = 20,
    include_full: bool = False,
    service: str | None = None,
) -> SearchResult:
    """按关键词搜索日志，支持时间范围和级别过滤"""
    limit = min(limit, settings.limits.max_lines)
    level = _normalize_level(level)

    now = datetime.now()
    if end_time:
        end_dt = datetime.fromisoformat(end_time)
    else:
        end_dt = now
    if start_time:
        start_dt = datetime.fromisoformat(start_time)
    else:
        start_dt = end_dt - timedelta(hours=1)

    hours_diff = (end_dt - start_dt).total_seconds() / 3600
    if hours_diff > settings.limits.max_time_range_hours:
        raise ValueError(
            f"时间范围 {hours_diff:.1f}h 超过上限 {settings.limits.max_time_range_hours}h"
        )

    params = {
        "keyword": keyword,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "level": level,
        "limit": limit,
        "include_full": include_full,
        "service": service,
    }

    try:
        files = file_adapter.get_hourly_files(start_dt, end_dt)
        if not files:
            _audit("search_logs", params, 0, False)
            return SearchResult(
                query=params,
                summary={"total_matches": 0, "returned": 0, "truncated": False},
                items=[],
            )

        if service:
            pattern = _service_log_pattern(service, level=level, keyword=keyword)
            results = await file_adapter.grep_files(
                files,
                pattern,
                limit,
                ["-E"],
                include_full_lines=include_full,
            )
        elif level:
            pattern = _level_keyword_pattern(level, keyword)
            results = await file_adapter.grep_files(
                files,
                pattern,
                limit,
                ["-E"],
                include_full_lines=include_full,
            )
        else:
            results = await file_adapter.grep_files(
                files,
                keyword,
                limit,
                include_full_lines=include_full,
            )

        items = _filter_items(
            _grep_results_to_items(results, include_full=include_full),
            service=service,
            level=level,
        )
        total = len(items)
        truncated = len(results) >= limit

        _audit("search_logs", params, total, truncated)
        return SearchResult(
            query=params,
            summary={"total_matches": total, "returned": len(items), "truncated": truncated},
            items=items,
            next_actions=["context_around_match", "search_by_request_id"],
        )
    except Exception as e:
        _audit("search_logs", params, 0, False, str(e))
        raise


async def tail_errors(
    hours_back: int = 1,
    keyword: str | None = None,
    limit: int = 30,
    include_full: bool = False,
    service: str | None = None,
) -> SearchResult:
    """查看最近的错误日志"""
    limit = min(limit, settings.limits.max_lines)
    params = {
        "hours_back": hours_back,
        "keyword": keyword,
        "limit": limit,
        "include_full": include_full,
        "service": service,
    }

    try:
        files = file_adapter.get_recent_hourly_files(hours_back)
        if not files:
            _audit("tail_errors", params, 0, False)
            return SearchResult(
                query=params,
                summary={"total_matches": 0, "returned": 0, "truncated": False},
                items=[],
            )

        if service:
            pattern = _service_log_pattern(service, level="ERR", keyword=keyword)
        else:
            pattern = _level_keyword_pattern("ERR", keyword)
        raw_limit = _tail_scan_limit(limit, has_app_filter=True)
        results = await file_adapter.grep_files(
            files,
            pattern,
            raw_limit,
            ["-E"],
            from_end=True,
            include_full_lines=include_full,
        )

        items = _filter_items(
            _grep_results_to_items(results, include_full=include_full),
            service=service,
            level="ERR",
        )[-limit:]
        total = len(items)
        truncated = len(results) >= raw_limit or total >= limit

        _audit("tail_errors", params, total, truncated)
        return SearchResult(
            query=params,
            summary=_tail_summary(items, limit, truncated, files),
            items=items,
            next_actions=["context_around_match", "search_by_request_id"],
        )
    except Exception as e:
        _audit("tail_errors", params, 0, False, str(e))
        raise


async def tail_service_logs(
    service: str,
    hours_back: int = 1,
    level: str | None = None,
    keyword: str | None = None,
    limit: int = 200,
    include_full: bool = False,
    exclude_noise: bool = False,
) -> SearchResult:
    """按服务查看最近日志。"""
    limit = min(limit, settings.limits.max_lines)
    level = _normalize_level(level)
    params = {
        "service": service,
        "hours_back": hours_back,
        "level": level,
        "keyword": keyword,
        "limit": limit,
        "include_full": include_full,
        "exclude_noise": exclude_noise,
    }

    try:
        files = file_adapter.get_recent_hourly_files(hours_back)
        if not files:
            _audit("tail_service_logs", params, 0, False)
            return SearchResult(
                query=params,
                summary={"total_matches": 0, "returned": 0, "truncated": False},
                items=[],
            )

        pattern = _service_log_pattern(service, level=level, keyword=keyword)
        raw_limit = _tail_scan_limit(limit, has_app_filter=bool(level or exclude_noise))
        results = await file_adapter.grep_files(
            files,
            pattern,
            raw_limit,
            ["-E"],
            from_end=True,
            include_full_lines=include_full,
        )

        items = _filter_items(
            _grep_results_to_items(results, include_full=include_full),
            service=service,
            level=level,
            exclude_noise=exclude_noise,
        )[-limit:]
        total = len(items)
        truncated = len(results) >= raw_limit or total >= limit

        _audit("tail_service_logs", params, total, truncated)
        return SearchResult(
            query=params,
            summary=_tail_summary(items, limit, truncated, files),
            items=items,
            next_actions=["context_around_match", "search_by_request_id"],
        )
    except Exception as e:
        _audit("tail_service_logs", params, 0, False, str(e))
        raise


def get_context(file: str, line_number: int, before: int = 10, after: int = 10) -> dict:
    """读取某行日志的上下文"""
    before = min(before, 50)
    after = min(after, 50)

    params = {"file": file, "line_number": line_number, "before": before, "after": after}
    try:
        ctx = file_adapter.read_context(file, line_number, before, after)
        ctx["before"] = [_maybe_redact(line) for line in ctx["before"]]
        ctx["match"] = _maybe_redact(ctx["match"])
        ctx["after"] = [_maybe_redact(line) for line in ctx["after"]]

        _audit("context_around_match", params, 1, False)
        return {
            "file": file,
            "line_number": line_number,
            "context": ctx,
        }
    except Exception as e:
        _audit("context_around_match", params, 0, False, str(e))
        raise


async def get_services() -> dict:
    """获取服务列表 — 优先从 Atlas 获取，降级到本地 supervisor 扫描"""
    try:
        services = await _fetch_services_from_atlas()
        if services:
            _audit("list_services", {"source": "atlas"}, len(services), False)
            return {"services": services, "source": "atlas"}
    except Exception:
        pass

    # 降级：本地 supervisor 扫描
    services = file_adapter.list_supervisor_services()
    _audit("list_services", {"source": "local"}, len(services), False)
    return {"services": services, "source": "local"}


async def _fetch_services_from_atlas() -> list[str]:
    """从 Atlas HTTP API 获取服务列表"""
    import httpx
    from app.core.config import settings

    url = f"{settings.atlas.url}/api/services"
    async with httpx.AsyncClient(timeout=settings.atlas.timeout) as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            return [svc["name"] for svc in data.get("service", [])]
    return []
