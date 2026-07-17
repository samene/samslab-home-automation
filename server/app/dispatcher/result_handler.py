"""Processing a device's COMMAND_RESULT: validate against tracked state, complete or fail.

A result for a command this dispatcher isn't watching (already terminal, or
never dispatched by this process) is a duplicate/unknown result — logged and
dropped, never an error. The dispatcher never inspects ``result``/``error_message``
beyond forwarding them; it has no notion of what a command's result *means*.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.application.events.domain_events import CommandResultReceived
from app.dispatcher.interfaces import CommandLifecyclePort
from app.dispatcher.timeouts import TimeoutMonitor

logger: Any = structlog.get_logger("dispatcher.result_handler")


class ResultHandler:
    """React to COMMAND_RESULT events, updating command lifecycle and releasing tracking."""

    def __init__(self, *, gateway: CommandLifecyclePort, timeout_monitor: TimeoutMonitor) -> None:
        """Bind to the shared command gateway and execution-timeout tracker."""
        self._gateway = gateway
        self._timeout_monitor = timeout_monitor

    async def handle_result(self, event: CommandResultReceived) -> None:
        """Resolve one command's result, or drop a duplicate/unknown one."""
        item = self._timeout_monitor.resolve(event.command_id)
        if item is None:
            logger.info(
                "dispatcher_duplicate_or_unknown_result",
                command_id=str(event.command_id),
                device_id=str(event.device_id),
            )
            return
        if event.success:
            await self._gateway.complete_command(event.command_id, result=event.result)
        else:
            await self._gateway.fail_command(
                event.command_id, error_message=event.error_message or "Command failed"
            )
