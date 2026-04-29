from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.adapters import file_adapter
from app.core.config import load_settings
from app.services import log_service


@pytest.mark.asyncio
async def test_grep_files_from_end_returns_latest_matches(tmp_path, monkeypatch):
    log_file = tmp_path / "2026042912.log"
    log_file.write_text(
        "\n".join(
            [
                "svc(1,1) 04-29T12:00:01.0000 ERR source.go:1: first",
                "svc(1,1) 04-29T12:00:02.0000 INF source.go:2: skip",
                "svc(1,1) 04-29T12:00:03.0000 ERR source.go:3: second",
                "svc(1,1) 04-29T12:00:04.0000 ERR source.go:4: third",
                "svc(1,1) 04-29T12:00:05.0000 ERR source.go:5: " + ("x" * 70000),
            ]
        )
    )
    monkeypatch.setattr(file_adapter.settings.limits, "command_timeout_seconds", 5)

    results = await file_adapter.grep_files([log_file], "ERR", max_lines=3, from_end=True)

    assert [line_number for _, line_number, _ in results] == [3, 4, 5]
    assert results[-1][2].endswith("字符]")

    full_results = await file_adapter.grep_files(
        [log_file],
        "ERR",
        max_lines=1,
        from_end=True,
        include_full_lines=True,
    )
    assert len(full_results[-1][2]) > 70000


def test_recent_hourly_files_use_configured_log_timezone(tmp_path, monkeypatch):
    (tmp_path / "2026042911.log").touch()
    (tmp_path / "2026042912.log").touch()
    (tmp_path / "2026042904.log").touch()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 4, 29, 4, 30, tzinfo=ZoneInfo("UTC"))
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)

    monkeypatch.setattr(file_adapter, "datetime", FixedDateTime)
    monkeypatch.setattr(file_adapter.settings.paths, "hourly_log_dir", str(tmp_path))
    monkeypatch.setattr(file_adapter.settings.time, "log_timezone", "Asia/Shanghai")

    files = file_adapter.get_recent_hourly_files(hours_back=1)

    assert [path.name for path in files] == ["2026042911.log", "2026042912.log"]


def test_load_settings_honors_probe_config_env(tmp_path, monkeypatch):
    config = tmp_path / "probe.yaml"
    config.write_text("time:\n  log_timezone: UTC\n")
    monkeypatch.setenv("MERIDIAN_PROBE_CONFIG", str(config))

    loaded = load_settings()

    assert loaded.time.log_timezone == "UTC"


@pytest.mark.asyncio
async def test_service_log_pattern_matches_only_service_prefix(tmp_path):
    log_file = tmp_path / "2026042912.log"
    log_file.write_text(
        "\n".join(
            [
                "jzadapter(1,1) 04-29T12:00:01.0000 INF source.go:1: started",
                "hlopen(1,1) 04-29T12:00:02.0000 ERR source.go:2: jzadapter failed",
                "jzadapter(1,1) 04-29T12:00:03.0000 ERR source.go:3: failed",
                "jzadapter(1,1) 04-29T12:00:04.0000 <TV34ERR2SRiqwVDezxkA> INF source.go:4: request id contains ERR",
            ]
        )
    )

    pattern = log_service._service_log_pattern("jzadapter", level="ERR")
    results = await file_adapter.grep_files([log_file], pattern, max_lines=10, extra_args=["-E"], from_end=True)

    assert [line_number for _, line_number, _ in results] == [3]


@pytest.mark.asyncio
async def test_level_pattern_does_not_match_err_inside_request_id(tmp_path):
    log_file = tmp_path / "2026042912.log"
    log_file.write_text(
        "\n".join(
            [
                "hlopen(1,1) 04-29T12:00:01.0000 <TV34ERR2SRiqwVDezxkA> INF source.go:1: ok",
                "hlopen(1,1) 04-29T12:00:02.0000 ERR source.go:2: failed",
            ]
        )
    )

    pattern = log_service._level_keyword_pattern("ERR")
    results = await file_adapter.grep_files([log_file], pattern, max_lines=10, extra_args=["-E"], from_end=True)

    assert [line_number for _, line_number, _ in results] == [2]


@pytest.mark.asyncio
async def test_search_by_request_id_falls_back_to_hourly_logs(tmp_path, monkeypatch):
    request_id = "x795vTUEvhiqwxF7krUA"
    log_file = tmp_path / "2026042915.log"
    log_file.write_text(
        "\n".join(
            [
                f"dbproxy(1,1) 04-29T15:39:36.1605 <{request_id}> ERR table_info.go:71:fetchTableColumn err:errcode 16005, errmsg ErrTableNotCreate",
                f"dbproxy(1,1) 04-29T15:39:36.1606 INF rpc.go:1546: ctx {request_id},,,hlwwmsgreach,172.31.0.16,2,0,0 path /dbproxy/AddObjectType code 0 req {{object_type:{{name:\"hlwwmsgreach.SopSetting\"}}}} rsp {{object_type:null}} time 1",
            ]
        )
    )

    async def empty_glog(_request_id: str, _back_hours: int = 0) -> str:
        return ""

    monkeypatch.setattr(log_service.glog_adapter, "glog_search", empty_glog)
    monkeypatch.setattr(file_adapter.settings.limits, "max_lines", 20)
    monkeypatch.setattr(file_adapter.settings.limits, "command_timeout_seconds", 5)
    monkeypatch.setattr(file_adapter.settings.paths, "hourly_log_dir", str(tmp_path))
    monkeypatch.setattr(file_adapter, "get_recent_hourly_files", lambda _hours_back: [log_file])

    result = await log_service.search_by_request_id(request_id, back_hours=1)

    assert result.total_lines == 2
    assert result.services == ["dbproxy"]
    assert result.error_count == 1
    assert "已自动降级" in result.hint
    assert "ErrTableNotCreate" in result.errors[0].message


@pytest.mark.asyncio
async def test_search_by_request_id_can_return_full_glog_lines(monkeypatch):
    request_id = "x795vTUEvhiqwxF7krUA"

    async def fake_glog(_request_id: str, _back_hours: int = 0) -> str:
        return "\n".join(
            [
                f"dbproxy(1,1) 04-29T15:39:36.1605 <{request_id}> \x1b[91mERR table_info.go:71:fetchTableColumn\x1b[0m err:errcode 16005, errmsg ErrTableNotCreate",
                f"dbproxy(1,1) 04-29T15:39:36.1606 \x1b[92mINF rpc.go:1546:\x1b[0m ctx {request_id},,,hlwwmsgreach,172.31.0.16,2,0,0 path /dbproxy/AddObjectType code 0 req {{object_type:{{name:\"hlwwmsgreach.SopSetting\"}}}} rsp {{object_type:null}} time 1",
            ]
        )

    monkeypatch.setattr(log_service.glog_adapter, "glog_search", fake_glog)

    result = await log_service.search_by_request_id(request_id, hint_time="15:39:36", include_full=True)

    assert result.total_lines == 2
    assert len(result.raw_lines) == 2
    assert "hlwwmsgreach.SopSetting" in result.raw_lines[1]
    assert "\x1b" not in result.raw_lines[0]
    assert "[91m" not in result.raw_lines[0]


def test_noise_filter_keeps_errors():
    items = log_service._filter_items(
        [
            log_service.LogItem(
                timestamp="04-29T12:00:01.0000",
                level="INF",
                service="hlopen",
                source="source.go:1:",
                text="Register handler success",
                file="",
                line_number=1,
            ),
            log_service.LogItem(
                timestamp="04-29T12:00:02.0000",
                level="ERR",
                service="hlopen",
                source="source.go:2:",
                text="Register failed",
                file="",
                line_number=2,
            ),
        ],
        service="hlopen",
        exclude_noise=True,
    )

    assert [item.line_number for item in items] == [2]


def test_tail_summary_marks_stale_latest_match(tmp_path, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 4, 29, 16, 13, tzinfo=ZoneInfo("Asia/Shanghai"))
            return current if tz else current.replace(tzinfo=None)

    monkeypatch.setattr(log_service, "datetime", FixedDateTime)
    item = log_service.LogItem(
        timestamp="04-29T15:25:34.7873",
        level="INF",
        service="hlopen",
        source="rpc.go:1546:",
        text="ok",
        file="/data/brick/log/2026042915.log",
        line_number=139735,
    )

    summary = log_service._tail_summary([item], limit=200, truncated=False, files=[tmp_path / "2026042916.log"])

    assert summary["stale"] is True
    assert summary["latest_age_seconds"] > 2700
    assert "不代表服务当前仍在产生日志" in summary["hint"]


def test_context_strips_ansi_sequences(tmp_path, monkeypatch):
    log_file = tmp_path / "2026042916.log"
    log_file.write_text(
        "\n".join(
            [
                "dbproxy(1,1) 04-29T16:34:33.0443 \x1b[92mINF rpc.go:1546:\x1b[0m ctx ok",
                "wwbase(1,1) 04-29T16:34:33.0445 [92mINF rpc.go:1546:[0m ctx ok",
            ]
        )
    )
    monkeypatch.setattr(file_adapter.settings.paths, "hourly_log_dir", str(tmp_path))

    result = log_service.get_context(str(log_file), line_number=1, before=0, after=1)

    assert "\x1b" not in result["context"]["match"]
    assert "[92m" not in result["context"]["match"]
    assert "[0m" not in result["context"]["match"]
    assert "[92m" not in result["context"]["after"][0]
    assert "[0m" not in result["context"]["after"][0]
