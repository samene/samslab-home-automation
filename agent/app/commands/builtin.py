"""The four built-in ``system.*`` handlers — demonstrations of the framework, no hardware.

Each is stateless and takes no constructor dependencies: everything it needs
at call time arrives through ``CommandContext``, exactly like any future
GPIO/camera/scheduler handler would.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.commands.context import CommandContext
from app.commands.handler import CommandHandler
from app.commands.registry import CommandRegistry


class SystemEchoHandler(CommandHandler):
    """Returns the command's own arguments unchanged."""

    @property
    def command_type(self) -> str:
        return "system.echo"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """Any payload is accepted; there is nothing to validate."""

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return dict(arguments)


class SystemPingHandler(CommandHandler):
    """Returns liveness status, the current time, the agent version, and uptime."""

    @property
    def command_type(self) -> str:
        return "system.ping"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        now = datetime.now(UTC)
        uptime_seconds = (now - context.services.agent_started_at).total_seconds()
        return {
            "status": "ok",
            "timestamp": now.isoformat(),
            "agent_version": context.agent_version,
            "uptime_seconds": uptime_seconds,
        }


class SystemCapabilitiesHandler(CommandHandler):
    """Returns registered plugins, registered command handlers, capabilities, and versions."""

    @property
    def command_type(self) -> str:
        return "system.capabilities"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        plugin_manager = context.services.plugin_manager
        registry = context.services.registry
        return {
            "plugins": [
                {"name": plugin.name, "capabilities": list(plugin.capabilities)}
                for plugin in plugin_manager.plugins
            ],
            "command_handlers": sorted(
                handler.command_type for handler in registry.list_handlers()
            ),
            "capabilities": list(plugin_manager.capabilities()),
            "versions": {
                "agent_version": context.agent_version,
                "protocol_version": context.settings.protocol_version,
            },
        }


class SystemHealthHandler(CommandHandler):
    """Returns the local health subsystem's current report."""

    @property
    def command_type(self) -> str:
        return "system.health"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        report = context.services.health_service.check()
        return {
            "state": report.state.value,
            "checks": [
                {"name": check.name, "state": check.state.value, "detail": check.detail}
                for check in report.checks
            ],
        }


def register_builtin_handlers(registry: CommandRegistry) -> None:
    """Register every built-in ``system.*`` handler onto ``registry``."""
    registry.register(SystemEchoHandler())
    registry.register(SystemPingHandler())
    registry.register(SystemCapabilitiesHandler())
    registry.register(SystemHealthHandler())
