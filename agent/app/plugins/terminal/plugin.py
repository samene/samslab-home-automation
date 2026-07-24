"""The terminal plugin: lifecycle hooks and health reporting over a ``TerminalService``."""

from __future__ import annotations

from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.terminal.service import TerminalService


class TerminalPlugin(Plugin):
    """Advertises the ``terminal`` capability (only when enabled) and starts the idle watchdog."""

    name = "terminal"

    def __init__(self, terminal_service: TerminalService, *, enabled: bool) -> None:
        self._terminal_service = terminal_service
        self._enabled = enabled
        self.capabilities = ("terminal",) if enabled else ()

    async def on_startup(self) -> None:
        """Start the idle-session watchdog; a no-op session dict costs nothing when disabled."""
        self._terminal_service.start_watchdog()

    async def on_shutdown(self) -> None:
        """Terminate every open PTY so no shell process outlives the agent."""
        await self._terminal_service.shutdown()

    def check_health(self) -> PluginHealthCheck:
        """Always healthy: an idle or disabled terminal capability is not a degraded state."""
        detail = (
            f"enabled={self._enabled} active_sessions={self._terminal_service.active_session_count}"
        )
        return PluginHealthCheck(healthy=True, detail=detail)
