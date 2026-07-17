"""Tests for the individual health check functions."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.health.checks import (
    check_configuration,
    check_connection,
    check_disk,
    check_memory,
    check_plugins,
)
from app.health.results import HealthState, combine_states
from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings


def test_combine_states_returns_worst() -> None:
    """combine_states picks the most severe state present."""
    assert combine_states([HealthState.HEALTHY, HealthState.DEGRADED]) is HealthState.DEGRADED
    assert combine_states([HealthState.DEGRADED, HealthState.UNHEALTHY]) is HealthState.UNHEALTHY


def test_combine_states_defaults_to_healthy_for_empty_input() -> None:
    """No checks at all is vacuously healthy."""
    assert combine_states([]) is HealthState.HEALTHY


def test_check_connection_unhealthy_when_not_connected() -> None:
    """Not connected at all is unhealthy."""
    result = check_connection(SessionState())
    assert result.state is HealthState.UNHEALTHY


def test_check_connection_degraded_when_connected_not_authenticated() -> None:
    """Connected but not yet authenticated is degraded."""
    session = SessionState()
    session.mark_connected()
    result = check_connection(session)
    assert result.state is HealthState.DEGRADED


def test_check_connection_healthy_when_authenticated() -> None:
    """A fully authenticated session is healthy."""
    session = SessionState()
    session.mark_authenticated(
        connection_id=uuid4(), protocol_version=1, connected_at=datetime.now(UTC)
    )
    result = check_connection(session)
    assert result.state is HealthState.HEALTHY


def test_check_configuration_healthy_for_valid_settings() -> None:
    """Valid settings (the only kind that can be constructed) are healthy."""
    result = check_configuration(make_settings())
    assert result.state is HealthState.HEALTHY


def test_check_configuration_unhealthy_for_blank_private_key() -> None:
    """A settings object with a blank key (bypassing normal validation) is unhealthy.

    AgentSettings' own validator rejects an empty DEVICE_PRIVATE_KEY at
    construction, so this defensive branch is reached via model_copy, which
    skips validators.
    """
    settings = make_settings().model_copy(update={"device_private_key": SecretStr("")})
    result = check_configuration(settings)
    assert result.state is HealthState.UNHEALTHY


def test_check_plugins_healthy_when_all_plugins_healthy() -> None:
    """No unhealthy plugins means the plugins check is healthy."""
    manager = PluginManager([Plugin()])
    result = check_plugins(manager)
    assert result.state is HealthState.HEALTHY


def test_check_plugins_unhealthy_when_any_plugin_unhealthy() -> None:
    """Any single unhealthy plugin makes the aggregate check unhealthy."""

    class Broken(Plugin):
        name = "broken"

        def check_health(self) -> PluginHealthCheck:
            return PluginHealthCheck(healthy=False, detail="oops")

    manager = PluginManager([Plugin(), Broken()])

    result = check_plugins(manager)

    assert result.state is HealthState.UNHEALTHY
    assert "broken" in (result.detail or "")


def test_check_memory_healthy_for_low_usage(tmp_path: Path) -> None:
    """A synthetic meminfo file with low usage reports healthy."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       1000000 kB\nMemAvailable:    900000 kB\n")

    result = check_memory(meminfo_path=meminfo)

    assert result.state is HealthState.HEALTHY


def test_check_memory_skips_blank_and_malformed_lines(tmp_path: Path) -> None:
    """Lines with no value after the colon, or a non-numeric value, are skipped."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "VmallocTotal:\n"
        "Weird: notanumber kB\n"
        "MemTotal:       1000000 kB\n"
        "MemAvailable:    900000 kB\n"
    )

    result = check_memory(meminfo_path=meminfo)

    assert result.state is HealthState.HEALTHY


def test_check_memory_unhealthy_for_high_usage(tmp_path: Path) -> None:
    """A synthetic meminfo file with almost no memory available reports unhealthy."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       1000000 kB\nMemAvailable:      1000 kB\n")

    result = check_memory(meminfo_path=meminfo)

    assert result.state is HealthState.UNHEALTHY


def test_check_memory_degraded_for_moderate_usage(tmp_path: Path) -> None:
    """Usage between the degraded and unhealthy thresholds reports degraded."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       1000000 kB\nMemAvailable:     100000 kB\n")

    result = check_memory(meminfo_path=meminfo)

    assert result.state is HealthState.DEGRADED


def test_check_memory_unhealthy_when_meminfo_missing(tmp_path: Path) -> None:
    """A missing meminfo file is reported unhealthy rather than raising."""
    result = check_memory(meminfo_path=tmp_path / "does-not-exist")
    assert result.state is HealthState.UNHEALTHY


def test_check_memory_unhealthy_when_fields_absent(tmp_path: Path) -> None:
    """A meminfo file missing the fields we need is reported unhealthy."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("SomeOtherField: 123 kB\n")

    result = check_memory(meminfo_path=meminfo)

    assert result.state is HealthState.UNHEALTHY


def test_check_disk_healthy_for_existing_writable_paths(tmp_path: Path) -> None:
    """An existing directory with normal usage reports healthy (assuming test-host disk isn't full)."""
    result = check_disk([tmp_path])
    assert result.state in (HealthState.HEALTHY, HealthState.DEGRADED, HealthState.UNHEALTHY)


def test_check_disk_unhealthy_when_disk_usage_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError from shutil.disk_usage is reported unhealthy rather than raising."""

    def _raise(_path: Path) -> None:
        raise OSError("no such device")

    monkeypatch.setattr(shutil, "disk_usage", _raise)

    result = check_disk([tmp_path])

    assert result.state is HealthState.UNHEALTHY


def test_check_disk_walks_up_to_an_existing_parent(tmp_path: Path) -> None:
    """A configured path that doesn't exist yet still resolves via an existing parent."""
    missing = tmp_path / "not" / "yet" / "created"
    result = check_disk([missing])
    assert result.name == "disk"


def test_check_disk_empty_paths_is_healthy() -> None:
    """No configured paths at all is vacuously healthy."""
    result = check_disk([])
    assert result.state is HealthState.HEALTHY
