from app.core.config import (
    ProbeLogDiscoveryConfig,
    ServiceDiscoveryConfig,
    Settings,
)
from app.main import _setup_discovery_providers
from app.services import service_discovery


def test_default_discovery_includes_probe_logs():
    settings = Settings()

    assert settings.probe_logs.enabled is True
    assert settings.discovery.providers == ["supervisor", "static", "probe_logs"]


def test_probe_logs_auto_appended_when_enabled_but_missing(monkeypatch):
    settings = Settings(
        probe_logs=ProbeLogDiscoveryConfig(enabled=True, base_url="http://probe:3002"),
        discovery=ServiceDiscoveryConfig(providers=["static"]),
    )

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    service_discovery.clear()
    try:
        _setup_discovery_providers()

        assert service_discovery.list_providers() == ["static", "probe_logs"]
    finally:
        service_discovery.clear()
