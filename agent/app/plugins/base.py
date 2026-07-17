"""The plugin base class. No real plugin exists yet — this is the framework
future GPIO/camera/scheduler drivers will register against."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginHealthCheck:
    """One plugin's self-reported health."""

    healthy: bool
    detail: str | None = None


class Plugin:
    """Base class for an agent plugin.

    Every hook has a safe default, so a subclass only overrides what it needs.
    ``capabilities`` are advertised to the server in HELLO's payload.
    """

    name: str = "plugin"
    capabilities: Sequence[str] = ()

    async def on_startup(self) -> None:
        """Called once during agent startup, after the framework itself is ready."""

    async def on_shutdown(self) -> None:
        """Called once during agent shutdown, before the connection is closed."""

    def check_health(self) -> PluginHealthCheck:
        """Return this plugin's own health; defaults to healthy with no detail."""
        return PluginHealthCheck(healthy=True)
