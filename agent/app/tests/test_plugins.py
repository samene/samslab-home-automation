"""Tests for the plugin framework: base class defaults and PluginManager coordination."""

from __future__ import annotations

import pytest

from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.registry import PluginManager


@pytest.mark.asyncio
async def test_default_plugin_hooks_are_no_ops() -> None:
    """The base Plugin class's hooks do nothing and its health check is healthy."""
    plugin = Plugin()
    await plugin.on_startup()
    await plugin.on_shutdown()
    assert plugin.check_health() == PluginHealthCheck(healthy=True)


def test_plugin_manager_starts_empty() -> None:
    """A fresh PluginManager has no plugins or capabilities."""
    manager = PluginManager()
    assert manager.plugins == ()
    assert manager.capabilities() == ()


def test_register_adds_a_plugin() -> None:
    """register() appends to the managed plugin set."""
    manager = PluginManager()
    plugin = Plugin()
    manager.register(plugin)
    assert manager.plugins == (plugin,)


def test_capabilities_deduplicates_across_plugins() -> None:
    """The union of capabilities preserves order and drops duplicates."""

    class First(Plugin):
        name = "first"
        capabilities = ("gpio", "shared")

    class Second(Plugin):
        name = "second"
        capabilities = ("shared", "camera")

    manager = PluginManager([First(), Second()])

    assert manager.capabilities() == ("gpio", "shared", "camera")


@pytest.mark.asyncio
async def test_startup_runs_in_registration_order() -> None:
    """Startup hooks run in the order plugins were registered."""
    order: list[str] = []

    class Recorder(Plugin):
        def __init__(self, name: str) -> None:
            self.name = name

        async def on_startup(self) -> None:
            order.append(self.name)

    manager = PluginManager([Recorder("a"), Recorder("b")])

    await manager.startup()

    assert order == ["a", "b"]


@pytest.mark.asyncio
async def test_shutdown_runs_in_reverse_registration_order() -> None:
    """Shutdown hooks run in reverse order, tearing down dependents first."""
    order: list[str] = []

    class Recorder(Plugin):
        def __init__(self, name: str) -> None:
            self.name = name

        async def on_shutdown(self) -> None:
            order.append(self.name)

    manager = PluginManager([Recorder("a"), Recorder("b")])

    await manager.shutdown()

    assert order == ["b", "a"]


def test_check_health_reports_per_plugin_by_name() -> None:
    """check_health returns each plugin's own health, keyed by name."""

    class Healthy(Plugin):
        name = "healthy-plugin"

    class Unhealthy(Plugin):
        name = "unhealthy-plugin"

        def check_health(self) -> PluginHealthCheck:
            return PluginHealthCheck(healthy=False, detail="broken")

    manager = PluginManager([Healthy(), Unhealthy()])

    results = manager.check_health()

    assert results["healthy-plugin"].healthy is True
    assert results["unhealthy-plugin"] == PluginHealthCheck(healthy=False, detail="broken")
