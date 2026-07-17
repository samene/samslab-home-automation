"""Tests for HealthService's combined report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.health.results import HealthState
from app.health.service import HealthService
from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings


def test_health_service_reports_unhealthy_when_disconnected() -> None:
    """A brand new session (not connected) makes the overall report unhealthy."""
    service = HealthService(
        settings=make_settings(), session=SessionState(), plugin_manager=PluginManager()
    )

    report = service.check()

    assert report.state is HealthState.UNHEALTHY
    assert any(check.name == "connection" for check in report.checks)


def test_health_service_reports_healthy_when_fully_connected(tmp_path: Path) -> None:
    """An authenticated session with no plugins is healthy overall, memory/disk permitting."""
    session = SessionState()
    session.mark_authenticated(
        connection_id=uuid4(), protocol_version=1, connected_at=datetime.now(UTC)
    )
    settings = make_settings(
        LOCAL_DATA_DIRECTORY=str(tmp_path),
        CACHE_DIRECTORY=str(tmp_path),
        TMP_DIRECTORY=str(tmp_path),
    )
    service = HealthService(settings=settings, session=session, plugin_manager=PluginManager())

    report = service.check()

    names = {check.name for check in report.checks}
    assert names == {"connection", "configuration", "plugins", "memory", "disk"}


def test_health_service_reflects_unhealthy_plugin() -> None:
    """An unhealthy plugin drags the overall report down even if connection is healthy."""

    class Broken(Plugin):
        name = "broken"

        def check_health(self) -> PluginHealthCheck:
            return PluginHealthCheck(healthy=False)

    session = SessionState()
    session.mark_authenticated(
        connection_id=uuid4(), protocol_version=1, connected_at=datetime.now(UTC)
    )
    service = HealthService(
        settings=make_settings(), session=session, plugin_manager=PluginManager([Broken()])
    )

    report = service.check()

    assert report.state is HealthState.UNHEALTHY
