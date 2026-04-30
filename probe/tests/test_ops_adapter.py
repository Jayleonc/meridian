import pytest

from app.adapters import ops_adapter
from app.services import log_service


@pytest.fixture(autouse=True)
def no_audit(monkeypatch):
    monkeypatch.setattr(log_service, "_audit", lambda *_args, **_kwargs: None)


@pytest.mark.asyncio
async def test_search_ops_logs_disabled_returns_unavailable(monkeypatch):
    monkeypatch.setattr(log_service.settings.ops, "enabled", False)

    result = await log_service.search_ops_logs(
        service="jzadapter",
        keyword="timeout",
        hours_back=1,
        hosts=["app-01"],
        limit=10,
    )

    assert result.summary["status"] == "unavailable"
    assert result.summary["available"] is False
    assert result.summary["partial"] is False
    assert result.items == []
    assert "未启用" in result.summary["reason"]


@pytest.mark.asyncio
async def test_search_ops_logs_rejects_too_many_hosts(monkeypatch):
    monkeypatch.setattr(log_service.settings.ops, "enabled", True)
    monkeypatch.setattr(log_service.settings.ops, "allowed_hosts", ["app-01", "app-02"])
    monkeypatch.setattr(log_service.settings.ops, "max_hosts", 1)

    with pytest.raises(ValueError, match="超过上限"):
        await log_service.search_ops_logs(
            service="jzadapter",
            keyword="timeout",
            hours_back=1,
            hosts=["app-01", "app-02"],
            limit=10,
        )


@pytest.mark.asyncio
async def test_search_ops_logs_rejects_unsafe_host(monkeypatch):
    monkeypatch.setattr(log_service.settings.ops, "enabled", True)
    monkeypatch.setattr(log_service.settings.ops, "allowed_hosts", ["app-01"])
    monkeypatch.setattr(log_service.settings.ops, "max_hosts", 5)

    with pytest.raises(ValueError, match="host 包含不安全字符"):
        await log_service.search_ops_logs(
            service="jzadapter",
            keyword="timeout",
            hours_back=1,
            hosts=["app-01;rm"],
            limit=10,
        )


@pytest.mark.asyncio
async def test_search_ops_logs_rejects_invalid_params(monkeypatch):
    monkeypatch.setattr(log_service.settings.ops, "enabled", True)
    monkeypatch.setattr(log_service.settings.ops, "allowed_hosts", ["app-01"])
    monkeypatch.setattr(log_service.settings.ops, "max_hosts", 5)

    with pytest.raises(ValueError, match="keyword 不能包含控制字符"):
        await log_service.search_ops_logs(
            service="jzadapter",
            keyword="bad\nkeyword",
            hours_back=1,
            hosts=["app-01"],
            limit=10,
        )

    with pytest.raises(ValueError, match="hours_back 必须"):
        await log_service.search_ops_logs(
            service="jzadapter",
            keyword="timeout",
            hours_back=0,
            hosts=["app-01"],
            limit=10,
        )


@pytest.mark.asyncio
async def test_search_ops_logs_expresses_partial_success(monkeypatch):
    async def fake_search_ops_logs(**_kwargs):
        return [
            ops_adapter.OpsHostOutput(
                host="app-01",
                stdout=(
                    "jzadapter(1,1) 04-30T10:20:30.0000 <req-1> "
                    "ERR source.go:1: timeout"
                ),
            ),
            ops_adapter.OpsHostOutput(host="app-02", error="timeout after 1s"),
        ]

    monkeypatch.setattr(log_service.settings.ops, "enabled", True)
    monkeypatch.setattr(log_service.ops_adapter, "search_ops_logs", fake_search_ops_logs)

    result = await log_service.search_ops_logs(
        service="jzadapter",
        keyword="timeout",
        hours_back=1,
        hosts=["app-01", "app-02"],
        limit=10,
    )

    assert result.summary["status"] == "partial"
    assert result.summary["partial"] is True
    assert result.summary["successful_hosts"] == ["app-01"]
    assert result.summary["failed_hosts"] == [{"host": "app-02", "reason": "timeout after 1s"}]
    assert result.failed_hosts[0].host == "app-02"
    assert result.items[0].host == "app-01"
    assert result.items[0].service == "jzadapter"
