"""Execution-timeout monitoring for commands that reached RUNNING.

A command that never produces a ``COMMAND_RESULT`` within its execution
window is transitioned to ``TIMEOUT`` — a distinct concern from the
acknowledgement timeout/retry loop in ``ack_manager.py``, which only covers
the DISPATCHED -> RUNNING leg.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

import structlog

from app.dispatcher.config import DispatcherConfig
from app.dispatcher.interfaces import CommandLifecyclePort
from app.dispatcher.metrics import (
    COMMAND_EXECUTION_SECONDS,
    DISPATCHER_TIMEOUTS_TOTAL,
    RUNNING_COMMANDS,
)
from app.dispatcher.queue import QueuedCommand

logger: Any = structlog.get_logger("dispatcher.timeouts")


@dataclass(slots=True)
class _RunningEntry:
    item: QueuedCommand
    deadline: float
    started_at: float


class TimeoutMonitor:
    """Track commands awaiting a result and time out any that run too long."""

    def __init__(self, *, gateway: CommandLifecyclePort, config: DispatcherConfig) -> None:
        """Bind to the shared command gateway and dispatcher configuration."""
        self._gateway = gateway
        self._config = config
        self._running: dict[UUID, _RunningEntry] = {}

    def track(self, item: QueuedCommand) -> None:
        """Start the execution-timeout window for a command that just began RUNNING."""
        now = monotonic()
        self._running[item.command_id] = _RunningEntry(
            item=item, deadline=now + self._config.execution_timeout_seconds, started_at=now
        )
        RUNNING_COMMANDS.set(len(self._running))

    def resolve(self, command_id: UUID) -> QueuedCommand | None:
        """Stop tracking a command once its result arrives; ``None`` if it wasn't tracked."""
        entry = self._running.pop(command_id, None)
        RUNNING_COMMANDS.set(len(self._running))
        if entry is None:
            return None
        COMMAND_EXECUTION_SECONDS.observe(monotonic() - entry.started_at)
        return entry.item

    def is_tracked(self, command_id: UUID) -> bool:
        """Return whether a command is currently being watched for an execution timeout."""
        return command_id in self._running

    def snapshot(self) -> list[QueuedCommand]:
        """Return every currently RUNNING command being watched, for admin introspection."""
        return [entry.item for entry in self._running.values()]

    async def run(self) -> None:
        """Sweep for expired execution windows until cancelled."""
        while True:
            await asyncio.sleep(self._config.sweep_interval_seconds)
            await self._sweep()

    async def _sweep(self) -> None:
        now = monotonic()
        for command_id, entry in list(self._running.items()):
            if now < entry.deadline:
                continue
            self._running.pop(command_id, None)
            RUNNING_COMMANDS.set(len(self._running))
            DISPATCHER_TIMEOUTS_TOTAL.inc()
            logger.warning(
                "dispatcher_command_execution_timeout",
                command_id=str(command_id),
                device_id=str(entry.item.device_id),
            )
            await self._gateway.mark_timeout(command_id)
