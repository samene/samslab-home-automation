"""Acknowledgement tracking, timeout detection, and retry-with-backoff for dispatched commands.

Covers exactly the DISPATCHED -> RUNNING leg: a command is tracked here from
the moment it is successfully handed to the WebSocket Gateway until either a
``COMMAND_ACK`` arrives (promoted to ``timeouts.py``'s execution-timeout
tracking) or its retry budget is exhausted (failed outright). Retries only
ever apply to this leg — a command already acknowledged is never retried.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

import structlog

from app.application.events.bus import EventBus
from app.application.events.domain_events import CommandAckReceived
from app.dispatcher.config import DispatcherConfig
from app.dispatcher.events import DispatchExhausted, DispatchRetryScheduled
from app.dispatcher.exceptions import DeliveryFailedError
from app.dispatcher.interfaces import CommandDeliveryPort, CommandLifecyclePort
from app.dispatcher.metrics import (
    COMMAND_ACK_LATENCY_SECONDS,
    DISPATCH_FAILURES_TOTAL,
    DISPATCHER_RETRIES_TOTAL,
)
from app.dispatcher.queue import QueuedCommand
from app.dispatcher.retries import compute_backoff_seconds, should_retry

logger: Any = structlog.get_logger("dispatcher.ack_manager")


@dataclass(slots=True)
class _PendingAck:
    item: QueuedCommand
    deadline: float
    dispatched_at: float
    retry_count: int = 0


class AckManager:
    """Track unacknowledged dispatches; retry with backoff, then give up."""

    def __init__(
        self,
        *,
        gateway: CommandLifecyclePort,
        delivery: CommandDeliveryPort,
        config: DispatcherConfig,
        on_running: Callable[[QueuedCommand], None],
        event_bus: EventBus | None = None,
    ) -> None:
        """Bind to the shared command gateway, delivery service, and config.

        ``on_running`` is called once a command is confirmed RUNNING, so the
        caller (the dispatcher composition root) can start execution-timeout
        tracking without this module needing to know ``timeouts.py`` exists.
        """
        self._gateway = gateway
        self._delivery = delivery
        self._config = config
        self._on_running = on_running
        self._event_bus = event_bus
        self._pending: dict[UUID, _PendingAck] = {}

    def track(self, item: QueuedCommand) -> None:
        """Start the acknowledgement-timeout window for a just-dispatched command."""
        now = monotonic()
        self._pending[item.command_id] = _PendingAck(
            item=item, deadline=now + self._config.ack_timeout_seconds, dispatched_at=now
        )

    def is_tracked(self, command_id: UUID) -> bool:
        """Return whether a command is currently awaiting acknowledgement."""
        return command_id in self._pending

    def untrack(self, command_id: UUID) -> None:
        """Stop tracking a command that was never actually delivered.

        Used when ``track()`` was called before attempting delivery (see
        ``worker.py``) and the send then failed, or ``mark_dispatched``
        turned out not to apply — the command was never really in flight, so
        this is neither an ack nor an exhaustion, just an undo.
        """
        self._pending.pop(command_id, None)

    def snapshot(self) -> list[QueuedCommand]:
        """Return every command currently awaiting acknowledgement, for admin introspection."""
        return [pending.item for pending in self._pending.values()]

    async def handle_ack(self, event: CommandAckReceived) -> None:
        """React to a device's COMMAND_ACK; a late or unknown ack is ignored, not fatal."""
        pending = self._pending.pop(event.command_id, None)
        if pending is None:
            logger.info(
                "dispatcher_late_or_unknown_ack",
                command_id=str(event.command_id),
                device_id=str(event.device_id),
            )
            return
        COMMAND_ACK_LATENCY_SECONDS.observe(monotonic() - pending.dispatched_at)
        command = await self._gateway.mark_running(event.command_id)
        if command is None:
            return
        self._on_running(pending.item)

    async def run(self) -> None:
        """Sweep for expired acknowledgement windows until cancelled."""
        while True:
            await asyncio.sleep(self._config.sweep_interval_seconds)
            await self._sweep()

    async def _sweep(self) -> None:
        now = monotonic()
        for command_id, pending in list(self._pending.items()):
            if now < pending.deadline:
                continue
            if should_retry(pending.retry_count, self._config.max_retries):
                await self._retry(command_id, pending, pending.retry_count + 1, now)
            else:
                await self._exhaust(command_id, pending)

    async def _retry(
        self, command_id: UUID, pending: _PendingAck, next_retry: int, now: float
    ) -> None:
        pending.retry_count = next_retry
        await self._gateway.record_retry(command_id)
        try:
            sent = await self._delivery.send_command(pending.item)
        except DeliveryFailedError:
            sent = False
        backoff = compute_backoff_seconds(
            next_retry,
            base_seconds=self._config.retry_backoff_base_seconds,
            max_seconds=self._config.retry_backoff_max_seconds,
        )
        pending.deadline = now + backoff
        DISPATCHER_RETRIES_TOTAL.inc()
        logger.warning(
            "dispatcher_ack_timeout_retry",
            command_id=str(command_id),
            device_id=str(pending.item.device_id),
            retry_count=pending.retry_count,
            resent=sent,
            backoff_seconds=backoff,
        )
        if self._event_bus is not None:
            await self._event_bus.publish(
                DispatchRetryScheduled(
                    command_id=command_id,
                    device_id=pending.item.device_id,
                    retry_count=pending.retry_count,
                    occurred_at=datetime.now(UTC),
                )
            )

    async def _exhaust(self, command_id: UUID, pending: _PendingAck) -> None:
        self._pending.pop(command_id, None)
        DISPATCH_FAILURES_TOTAL.inc()
        logger.warning(
            "dispatcher_ack_retries_exhausted",
            command_id=str(command_id),
            device_id=str(pending.item.device_id),
            retry_count=pending.retry_count,
        )
        await self._gateway.fail_command(
            command_id,
            error_message=f"No acknowledgement received after {pending.retry_count} retries",
        )
        if self._event_bus is not None:
            await self._event_bus.publish(
                DispatchExhausted(
                    command_id=command_id,
                    device_id=pending.item.device_id,
                    retry_count=pending.retry_count,
                    occurred_at=datetime.now(UTC),
                )
            )
