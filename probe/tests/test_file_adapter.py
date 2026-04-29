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
            ]
        )
    )

    pattern = log_service._service_log_pattern("jzadapter", level="ERR")
    results = await file_adapter.grep_files([log_file], pattern, max_lines=10, extra_args=["-E"], from_end=True)

    assert [line_number for _, line_number, _ in results] == [3]
