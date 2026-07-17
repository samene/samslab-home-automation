"""Registers plugins and runs their lifecycle hooks and health checks."""

from __future__ import annotations

from collections.abc import Sequence

from app.plugins.base import Plugin, PluginHealthCheck


class PluginManager:
    """Owns the set of loaded plugins and coordinates their hooks.

    Startup hooks run in registration order; shutdown hooks run in reverse,
    so a plugin that depends on another started earlier is torn down first.
    """

    def __init__(self, plugins: Sequence[Plugin] = ()) -> None:
        self._plugins: list[Plugin] = list(plugins)

    def register(self, plugin: Plugin) -> None:
        """Add a plugin to the managed set."""
        self._plugins.append(plugin)

    @property
    def plugins(self) -> Sequence[Plugin]:
        """Every registered plugin, in registration order."""
        return tuple(self._plugins)

    def capabilities(self) -> tuple[str, ...]:
        """The union of every registered plugin's advertised capabilities, order-preserving."""
        seen: list[str] = []
        for plugin in self._plugins:
            for capability in plugin.capabilities:
                if capability not in seen:
                    seen.append(capability)
        return tuple(seen)

    async def startup(self) -> None:
        """Run every plugin's startup hook, in registration order."""
        for plugin in self._plugins:
            await plugin.on_startup()

    async def shutdown(self) -> None:
        """Run every plugin's shutdown hook, in reverse registration order."""
        for plugin in reversed(self._plugins):
            await plugin.on_shutdown()

    def check_health(self) -> dict[str, PluginHealthCheck]:
        """Collect every registered plugin's own health check, keyed by plugin name."""
        return {plugin.name: plugin.check_health() for plugin in self._plugins}
