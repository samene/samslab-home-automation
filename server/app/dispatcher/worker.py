"""The dispatch loop: discover pending commands, queue them, and attempt delivery.

A device that is not currently connected is never a failure — the command
is simply deferred to the next drain cycle (or, if it drops out of the
in-memory queue entirely, rediscovered on the next poll, since it is still
PENDING/QUEUED in the Command domain).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from app.application.events.bus import EventBus
from app.dispatcher.ack_manager import AckManager
from app.dispatcher.config import DispatcherConfig
from app.dispatcher.events import CommandQueued, DeliveryFailed
from app.dispatcher.exceptions import DeliveryFailedError
from app.dispatcher.interfaces import CommandDeliveryPort, CommandLifecyclePort
from app.dispatcher.metrics import (
    COMMANDS_DISPATCHED_TOTAL,
    DISPATCHER_QUEUE_DEPTH,
    PENDING_COMMANDS,
)
from app.dispatcher.queue import DispatchQueue, QueuedCommand

logger: Any = structlog.get_logger("dispatcher.worker")


class DispatchWorker:
    """Poll for pending commands, queue them by priority, and dispatch what it can."""

    def __init__(
        self,
        *,
        queue: DispatchQueue,
        gateway: CommandLifecyclePort,
        delivery: CommandDeliveryPort,
        ack_manager: AckManager,
        config: DispatcherConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        """Bind to the shared queue and the dispatcher's other collaborators."""
        self._queue = queue
        self._gateway = gateway
        self._delivery = delivery
        self._ack_manager = ack_manager
        self._config = config
        self._event_bus = event_bus

    async def run(self) -> None:
        """Poll, queue, and drain until cancelled."""
        while True:
            await self.poll_once()
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def poll_once(self) -> None:
        """Discover newly pending commands and attempt to dispatch everything queued.

        Exposed separately from ``run`` so tests (and any future manual
        trigger) can drive exactly one cycle deterministically.
        """
        await self._discover()
        await self._drain_queue()
        DISPATCHER_QUEUE_DEPTH.set(len(self._queue))

    async def _discover(self) -> None:
        pending = await self._gateway.list_pending(limit=self._config.discovery_batch_size)
        PENDING_COMMANDS.set(len(pending))
        now = datetime.now(UTC)
        for command in pending:
            if self._queue.contains(command.id) or self._ack_manager.is_tracked(command.id):
                continue
            self._queue.push(
                QueuedCommand(
                    command_id=command.id,
                    device_id=command.device_id,
                    priority=command.priority,
                    command_type=command.command_type,
                    payload=command.payload,
                    enqueued_at=now,
                )
            )
            if self._event_bus is not None:
                await self._event_bus.publish(
                    CommandQueued(
                        command_id=command.id, device_id=command.device_id, occurred_at=now
                    )
                )

    async def _drain_queue(self) -> None:
        deferred: list[QueuedCommand] = []
        while (item := self._queue.pop()) is not None:
            if not self._delivery.is_device_connected(item.device_id):
                deferred.append(item)
                continue
            await self._dispatch_one(item)
        for item in deferred:
            self._queue.push(item)

    async def _dispatch_one(self, item: QueuedCommand) -> None:
        """Track for acknowledgement *before* sending, not after.

        A device can validate and reply with COMMAND_ACK essentially as soon
        as it receives the envelope — faster, in practice, than this
        server's own ``mark_dispatched`` DB write reliably completes. Tracking
        only after both the send and that write left a real window where a
        genuinely-on-time ack arrived before ``ack_manager.track()`` had even
        run, was logged as "late or unknown", and silently dropped — leaving
        the command retried indefinitely despite the device already having
        moved on. Tracking first closes that window; a failed send or a
        ``mark_dispatched`` that turns out not to apply both explicitly
        untrack, since the command was never really in flight either way.
        """
        self._ack_manager.track(item)
        reason: str | None = None
        try:
            sent = await self._delivery.send_command(item)
        except DeliveryFailedError as error:
            sent = False
            reason = str(error)
        if not sent:
            self._ack_manager.untrack(item.command_id)
            logger.warning(
                "dispatcher_send_failed",
                command_id=str(item.command_id),
                device_id=str(item.device_id),
                reason=reason or "device_not_connected",
            )
            if self._event_bus is not None:
                await self._event_bus.publish(
                    DeliveryFailed(
                        command_id=item.command_id,
                        device_id=item.device_id,
                        reason=reason or "device_not_connected",
                        occurred_at=datetime.now(UTC),
                    )
                )
            return
        command = await self._gateway.mark_dispatched(item.command_id)
        if command is None:
            self._ack_manager.untrack(item.command_id)
            logger.info(
                "dispatcher_command_no_longer_dispatchable", command_id=str(item.command_id)
            )
            return
        COMMANDS_DISPATCHED_TOTAL.inc()
        logger.info(
            "dispatcher_command_dispatched",
            command_id=str(item.command_id),
            device_id=str(item.device_id),
            priority=item.priority.value,
        )
