"""Tests for DispatchWorker: discovery, queueing, and priority-respecting drain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.dispatcher.config import DispatcherConfig
from app.dispatcher.events import CommandQueued, DeliveryFailed
from app.dispatcher.exceptions import DeliveryFailedError
from app.dispatcher.queue import DispatchQueue, QueuedCommand
from app.dispatcher.worker import DispatchWorker
from app.domains.commands.models import CommandPriority


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


@dataclass
class _FakeCommand:
    id: UUID
    device_id: UUID
    priority: CommandPriority = CommandPriority.NORMAL
    command_type: str = "pump.start"
    payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.payload is None:
            self.payload = {}


class _FakeGateway:
    def __init__(self, pending: list[_FakeCommand] | None = None) -> None:
        self.pending = pending or []
        self.mark_dispatched_calls: list[UUID] = []
        self.mark_dispatched_result: object = "ok"

    async def list_pending(self, *, limit: int) -> list[_FakeCommand]:
        return self.pending[:limit]

    async def mark_dispatched(self, command_id: UUID) -> object:
        self.mark_dispatched_calls.append(command_id)
        return self.mark_dispatched_result


class _FakeDelivery:
    def __init__(
        self,
        *,
        connected: set[UUID] | None = None,
        send_result: bool = True,
        raise_delivery_failed: bool = False,
    ) -> None:
        self.connected = connected or set()
        self.send_result = send_result
        self.raise_delivery_failed = raise_delivery_failed
        self.send_calls: list[UUID] = []

    def is_device_connected(self, device_id: UUID) -> bool:
        return device_id in self.connected

    async def send_command(self, item: Any) -> bool:
        self.send_calls.append(item.command_id)
        if self.raise_delivery_failed:
            raise DeliveryFailedError("outgoing queue full")
        return self.send_result


class _FakeAckManager:
    def __init__(self) -> None:
        self.tracked: list[Any] = []
        self.tracked_ids: set[UUID] = set()
        self.untracked_ids: list[UUID] = []

    def is_tracked(self, command_id: UUID) -> bool:
        return command_id in self.tracked_ids

    def track(self, item: Any) -> None:
        self.tracked.append(item)
        self.tracked_ids.add(item.command_id)

    def untrack(self, command_id: UUID) -> None:
        self.untracked_ids.append(command_id)
        self.tracked_ids.discard(command_id)


def _config() -> DispatcherConfig:
    return DispatcherConfig(
        poll_interval_seconds=1.0,
        discovery_batch_size=100,
        ack_timeout_seconds=10.0,
        execution_timeout_seconds=60.0,
        max_retries=4,
        retry_backoff_base_seconds=1.0,
        retry_backoff_max_seconds=30.0,
        sweep_interval_seconds=1.0,
    )


def _queued_item(*, command_id: UUID, device_id: UUID) -> QueuedCommand:
    return QueuedCommand(
        command_id=command_id,
        device_id=device_id,
        priority=CommandPriority.NORMAL,
        command_type="pump.start",
        payload={},
        enqueued_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_discover_queues_newly_pending_commands() -> None:
    """A discovered pending command is added to the in-memory queue."""
    command = _FakeCommand(id=uuid4(), device_id=uuid4())
    queue = DispatchQueue()
    gateway = _FakeGateway(pending=[command])
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=_FakeDelivery(),
        ack_manager=_FakeAckManager(),  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._discover()
    assert queue.contains(command.id) is True


@pytest.mark.asyncio
async def test_discover_does_not_duplicate_an_already_queued_command() -> None:
    """Rediscovering a command already in the queue does not add a second copy."""
    command = _FakeCommand(id=uuid4(), device_id=uuid4())
    queue = DispatchQueue()
    gateway = _FakeGateway(pending=[command])
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=_FakeDelivery(),
        ack_manager=_FakeAckManager(),  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._discover()
    await worker._discover()
    assert len(queue) == 1


@pytest.mark.asyncio
async def test_discover_skips_a_command_already_tracked_for_acknowledgement() -> None:
    """A command already DISPATCHED and awaiting ack is never re-queued from discovery."""
    command = _FakeCommand(id=uuid4(), device_id=uuid4())
    queue = DispatchQueue()
    ack_manager = _FakeAckManager()
    ack_manager.tracked_ids.add(command.id)
    gateway = _FakeGateway(pending=[command])
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=_FakeDelivery(),
        ack_manager=ack_manager,  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._discover()
    assert len(queue) == 0


@pytest.mark.asyncio
async def test_drain_dispatches_to_a_connected_device() -> None:
    """A queued command for a connected device is sent, marked dispatched, and ack-tracked."""
    device_id = uuid4()
    command_id = uuid4()
    queue = DispatchQueue()
    queue.push(_queued_item(command_id=command_id, device_id=device_id))
    gateway = _FakeGateway()
    delivery = _FakeDelivery(connected={device_id})
    ack_manager = _FakeAckManager()
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        ack_manager=ack_manager,  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._drain_queue()

    assert delivery.send_calls == [command_id]
    assert gateway.mark_dispatched_calls == [command_id]
    assert len(ack_manager.tracked) == 1
    assert len(queue) == 0


@pytest.mark.asyncio
async def test_drain_defers_a_command_for_a_disconnected_device() -> None:
    """A command whose device is not connected is left queued for the next drain."""
    device_id = uuid4()
    item = _queued_item(command_id=uuid4(), device_id=device_id)
    queue = DispatchQueue()
    queue.push(item)
    gateway = _FakeGateway()
    delivery = _FakeDelivery(connected=set())  # nothing connected
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        ack_manager=_FakeAckManager(),  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._drain_queue()

    assert delivery.send_calls == []
    assert gateway.mark_dispatched_calls == []
    assert queue.contains(item.command_id) is True  # still there for the next cycle


@pytest.mark.asyncio
async def test_drain_does_not_track_when_send_fails() -> None:
    """A transport-level send failure never marks dispatched, and its speculative
    pre-send ack-tracking (see _dispatch_one's docstring) is undone, not left dangling."""
    device_id = uuid4()
    item = _queued_item(command_id=uuid4(), device_id=device_id)
    queue = DispatchQueue()
    queue.push(item)
    gateway = _FakeGateway()
    delivery = _FakeDelivery(connected={device_id}, send_result=False)
    ack_manager = _FakeAckManager()
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        ack_manager=ack_manager,  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._drain_queue()

    assert gateway.mark_dispatched_calls == []
    assert ack_manager.is_tracked(item.command_id) is False
    assert ack_manager.untracked_ids == [item.command_id]


@pytest.mark.asyncio
async def test_dispatch_handles_a_delivery_failed_error_like_a_failed_send() -> None:
    """A DeliveryFailedError (backpressure) from send_command is treated like a failed send."""
    device_id = uuid4()
    item = _queued_item(command_id=uuid4(), device_id=device_id)
    queue = DispatchQueue()
    queue.push(item)
    gateway = _FakeGateway()
    delivery = _FakeDelivery(connected={device_id}, raise_delivery_failed=True)
    ack_manager = _FakeAckManager()
    event_bus = _FakeEventBus()
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        ack_manager=ack_manager,  # type: ignore[arg-type]
        config=_config(),
        event_bus=event_bus,  # type: ignore[arg-type]
    )
    await worker._drain_queue()

    assert gateway.mark_dispatched_calls == []
    assert ack_manager.is_tracked(item.command_id) is False
    assert ack_manager.untracked_ids == [item.command_id]
    published = [event for event in event_bus.published if isinstance(event, DeliveryFailed)]
    assert len(published) == 1
    assert "queue full" in published[0].reason


@pytest.mark.asyncio
async def test_drain_skips_ack_tracking_when_mark_dispatched_is_not_applicable() -> None:
    """If mark_dispatched reports 'not applicable' (None), the earlier speculative
    ack-tracking is undone rather than left dangling."""
    device_id = uuid4()
    item = _queued_item(command_id=uuid4(), device_id=device_id)
    queue = DispatchQueue()
    queue.push(item)
    gateway = _FakeGateway()
    gateway.mark_dispatched_result = None
    delivery = _FakeDelivery(connected={device_id})
    ack_manager = _FakeAckManager()
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        ack_manager=ack_manager,  # type: ignore[arg-type]
        config=_config(),
    )
    await worker._drain_queue()

    assert ack_manager.is_tracked(item.command_id) is False
    assert ack_manager.untracked_ids == [item.command_id]


@pytest.mark.asyncio
async def test_discover_publishes_command_queued_when_a_bus_is_given() -> None:
    """A newly discovered command publishes CommandQueued on the event bus."""
    command = _FakeCommand(id=uuid4(), device_id=uuid4())
    queue = DispatchQueue()
    gateway = _FakeGateway(pending=[command])
    event_bus = _FakeEventBus()
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=_FakeDelivery(),
        ack_manager=_FakeAckManager(),  # type: ignore[arg-type]
        config=_config(),
        event_bus=event_bus,  # type: ignore[arg-type]
    )
    await worker._discover()
    assert len(event_bus.published) == 1
    published = event_bus.published[0]
    assert isinstance(published, CommandQueued)
    assert published.command_id == command.id


@pytest.mark.asyncio
async def test_dispatch_publishes_delivery_failed_when_send_fails() -> None:
    """A transport-level send failure publishes DeliveryFailed on the event bus."""
    device_id = uuid4()
    item = _queued_item(command_id=uuid4(), device_id=device_id)
    queue = DispatchQueue()
    queue.push(item)
    event_bus = _FakeEventBus()
    worker = DispatchWorker(
        queue=queue,
        gateway=_FakeGateway(),  # type: ignore[arg-type]
        delivery=_FakeDelivery(connected={device_id}, send_result=False),
        ack_manager=_FakeAckManager(),  # type: ignore[arg-type]
        config=_config(),
        event_bus=event_bus,  # type: ignore[arg-type]
    )
    await worker._drain_queue()
    assert len(event_bus.published) == 1
    published = event_bus.published[0]
    assert isinstance(published, DeliveryFailed)
    assert published.command_id == item.command_id


@pytest.mark.asyncio
async def test_poll_once_discovers_and_drains_in_one_cycle() -> None:
    """poll_once() runs discovery and drain together, dispatching what it can."""
    device_id = uuid4()
    command = _FakeCommand(id=uuid4(), device_id=device_id)
    queue = DispatchQueue()
    gateway = _FakeGateway(pending=[command])
    delivery = _FakeDelivery(connected={device_id})
    ack_manager = _FakeAckManager()
    worker = DispatchWorker(
        queue=queue,
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        ack_manager=ack_manager,  # type: ignore[arg-type]
        config=_config(),
    )
    await worker.poll_once()

    assert gateway.mark_dispatched_calls == [command.id]
    assert len(queue) == 0
