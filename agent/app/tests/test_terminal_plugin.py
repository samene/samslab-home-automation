"""Tests for TerminalPlugin: capability advertisement and lifecycle hooks."""

from __future__ import annotations

from uuid import uuid4

from app.plugins.terminal.plugin import TerminalPlugin
from app.plugins.terminal.service import TerminalService
from app.tests.conftest import make_settings
from app.tests.test_terminal_service import FakeSender, _open_envelope


def _plugin(*, enabled: bool) -> tuple[TerminalPlugin, TerminalService]:
    settings = make_settings(TERMINAL_ENABLED=enabled, TERMINAL_SHELL="/bin/sh")
    service = TerminalService(settings, send=FakeSender())
    return TerminalPlugin(service, enabled=enabled), service


def test_advertises_the_terminal_capability_when_enabled() -> None:
    plugin, _service = _plugin(enabled=True)
    assert plugin.name == "terminal"
    assert "terminal" in plugin.capabilities


def test_does_not_advertise_the_capability_when_disabled() -> None:
    plugin, _service = _plugin(enabled=False)
    assert plugin.capabilities == ()


async def test_on_startup_starts_the_idle_watchdog_without_raising() -> None:
    plugin, _service = _plugin(enabled=True)

    await plugin.on_startup()  # must not raise

    await plugin.on_shutdown()


async def test_on_shutdown_terminates_every_open_session() -> None:
    plugin, service = _plugin(enabled=True)
    await plugin.on_startup()
    await service.handle_open(_open_envelope(uuid4()))
    assert service.active_session_count == 1

    await plugin.on_shutdown()

    assert service.active_session_count == 0


def test_check_health_reports_enabled_state_and_session_count() -> None:
    plugin, _service = _plugin(enabled=True)

    result = plugin.check_health()

    assert result.healthy is True
    assert "enabled=True" in (result.detail or "")
    assert "active_sessions=0" in (result.detail or "")
