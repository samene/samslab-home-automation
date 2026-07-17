"""Tests for AckManager: ack tracking, late/unknown acks, retry-with-backoff, and exhaustion."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.application.events.domain_events import CommandAckReceived
from app.dispatcher.ack_manager import AckManager
from app.dispatcher.config import DispatcherConfig
from app.dispatcher.events import DispatchExhausted, DispatchRetryScheduled
from app.dispatcher.exceptions import DeliveryFailedError
from app.dispatcher.queue import QueuedCommand
from app.domains.commands.models import CommandPriority


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


class _FakeGateway:
    """Implements only what AckManager actually calls; the rest satisfies the Protocol shape."""

    def __init__(self, *, mark_running_result: object = "ok") -> None:
        self.mark_running_calls: list[object] = []
        self.record_retry_calls: list[object] = []
        self.fail_command_calls: list[tuple[object, str]] = []
        self._mark_running_result = mark_running_result

    async def list_pending(self, *, limit: int) -> list[object]:
        raise NotImplementedError("not exercised by AckManager")

    async def mark_dispatched(self, command_id: object) -> object:
        raise NotImplementedError("not exercised by AckManager")

    async def mark_running(self, command_id: object) -> object:
        self.mark_running_calls.append(command_id)
        return self._mark_running_result

    async def mark_timeout(self, command_id: object) -> object:
        raise NotImplementedError("not exercised by AckManager")

    async def record_retry(self, command_id: object) -> object:
        self.record_retry_calls.append(command_id)
        return object()

    async def complete_command(self, command_id: object, *, result: dict[str, object]) -> object:
        raise NotImplementedError("not exercised by AckManager")

    async def fail_command(self, command_id: object, *, error_message: str) -> object:
        self.fail_command_calls.append((command_id, error_message))
        return object()


class _FakeDelivery:
    def __init__(self, *, send_result: bool = True, raise_delivery_failed: bool = False) -> None:
        self.send_calls: list[QueuedCommand] = []
        self.send_result = send_result
        self.raise_delivery_failed = raise_delivery_failed

    def is_device_connected(self, device_id: object) -> bool:
        return True

    async def send_command(self, item: QueuedCommand) -> bool:
        self.send_calls.append(item)
        if self.raise_delivery_failed:
            raise DeliveryFailedError("outgoing queue full")
        return self.send_result


def _config(**overrides: Any) -> DispatcherConfig:
    base: dict[str, Any] = dict(
        poll_interval_seconds=1.0,
        discovery_batch_size=100,
        ack_timeout_seconds=0.03,
        execution_timeout_seconds=60.0,
        max_retries=4,
        retry_backoff_base_seconds=0.02,
        retry_backoff_max_seconds=1.0,
        sweep_interval_seconds=0.02,
    )
    base.update(overrides)
    return DispatcherConfig(**base)


def _item() -> QueuedCommand:
    return QueuedCommand(
        command_id=uuid4(),
        device_id=uuid4(),
        priority=CommandPriority.NORMAL,
        command_type="pump.start",
        payload={},
        enqueued_at=datetime.now(UTC),
    )


async def _run_sweeper_briefly(manager: AckManager, *, duration: float = 0.3) -> None:
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(duration)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_track_marks_a_command_as_awaiting_acknowledgement() -> None:
    """A tracked command is reported as tracked until resolved."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(),
        on_running=lambda item: None,
    )
    item = _item()
    manager.track(item)
    assert manager.is_tracked(item.command_id) is True
    assert manager.snapshot() == [item]


def test_untrack_removes_a_command_that_was_never_really_in_flight() -> None:
    """untrack() undoes a speculative pre-send track() (see worker.py's _dispatch_one)
    without treating it as an ack or an exhausted retry budget."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(),
        on_running=lambda item: None,
    )
    item = _item()
    manager.track(item)
    manager.untrack(item.command_id)
    assert manager.is_tracked(item.command_id) is False
    assert manager.snapshot() == []


def test_untrack_an_unknown_command_is_a_no_op() -> None:
    """untrack() for a command never tracked (or already resolved) does nothing."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(),
        on_running=lambda item: None,
    )
    manager.untrack(uuid4())


@pytest.mark.asyncio
async def test_handle_ack_resolves_tracking_and_marks_running() -> None:
    """A COMMAND_ACK before the deadline resolves tracking and promotes to RUNNING."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    promoted: list[QueuedCommand] = []
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(),
        on_running=promoted.append,
    )
    item = _item()
    manager.track(item)

    await manager.handle_ack(
        CommandAckReceived(
            command_id=item.command_id,
            device_id=item.device_id,
            message_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )
    )

    assert manager.is_tracked(item.command_id) is False
    assert gateway.mark_running_calls == [item.command_id]
    assert promoted == [item]


@pytest.mark.asyncio
async def test_handle_ack_for_an_untracked_command_is_ignored() -> None:
    """A late or unknown ack does not call mark_running or crash."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(),
        on_running=lambda item: None,
    )

    await manager.handle_ack(
        CommandAckReceived(
            command_id=uuid4(),
            device_id=uuid4(),
            message_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )
    )

    assert gateway.mark_running_calls == []


@pytest.mark.asyncio
async def test_handle_ack_when_mark_running_is_not_applicable_does_not_promote() -> None:
    """If mark_running reports 'not applicable' (None), on_running is never called."""
    gateway = _FakeGateway(mark_running_result=None)
    delivery = _FakeDelivery()
    promoted: list[QueuedCommand] = []
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(),
        on_running=promoted.append,
    )
    item = _item()
    manager.track(item)

    await manager.handle_ack(
        CommandAckReceived(
            command_id=item.command_id,
            device_id=item.device_id,
            message_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )
    )

    assert promoted == []


@pytest.mark.asyncio
async def test_sweep_retries_an_unacknowledged_command_with_backoff() -> None:
    """An expired ack deadline triggers a retry: record_retry + resend + new deadline."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    # A large backoff relative to the test window guarantees exactly one retry fires,
    # regardless of scheduling jitter between sweep ticks.
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(retry_backoff_base_seconds=0.3),
        on_running=lambda item: None,
    )
    item = _item()
    manager.track(item)

    await _run_sweeper_briefly(manager, duration=0.12)

    assert gateway.record_retry_calls == [item.command_id]
    assert delivery.send_calls == [item]
    assert manager.is_tracked(item.command_id) is True  # still tracked, awaiting the next attempt


@pytest.mark.asyncio
async def test_sweep_exhausts_retries_and_fails_the_command() -> None:
    """Once max_retries is reached, the command is failed and untracked."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(max_retries=1),
        on_running=lambda item: None,
    )
    item = _item()
    manager.track(item)

    await _run_sweeper_briefly(manager, duration=0.5)

    assert manager.is_tracked(item.command_id) is False
    assert len(gateway.fail_command_calls) == 1
    failed_id, message = gateway.fail_command_calls[0]
    assert failed_id == item.command_id
    assert "1" in message


@pytest.mark.asyncio
async def test_sweep_publishes_dispatch_retry_scheduled_when_a_bus_is_given() -> None:
    """A retry attempt publishes DispatchRetryScheduled on the event bus."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    event_bus = _FakeEventBus()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(retry_backoff_base_seconds=0.3),
        on_running=lambda item: None,
        event_bus=event_bus,  # type: ignore[arg-type]
    )
    item = _item()
    manager.track(item)

    await _run_sweeper_briefly(manager, duration=0.12)

    assert len(event_bus.published) == 1
    published = event_bus.published[0]
    assert isinstance(published, DispatchRetryScheduled)
    assert published.command_id == item.command_id
    assert published.retry_count == 1


@pytest.mark.asyncio
async def test_sweep_publishes_dispatch_exhausted_when_a_bus_is_given() -> None:
    """Exhausting retries publishes DispatchExhausted on the event bus."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery()
    event_bus = _FakeEventBus()
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(max_retries=1),
        on_running=lambda item: None,
        event_bus=event_bus,  # type: ignore[arg-type]
    )
    item = _item()
    manager.track(item)

    await _run_sweeper_briefly(manager, duration=0.5)

    exhausted = [event for event in event_bus.published if isinstance(event, DispatchExhausted)]
    assert len(exhausted) == 1
    assert exhausted[0].command_id == item.command_id


@pytest.mark.asyncio
async def test_sweep_retries_even_when_resend_fails() -> None:
    """A retry attempt that itself fails to send (e.g. device disconnected) still reschedules."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery(send_result=False)
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(max_retries=4, retry_backoff_base_seconds=0.3),
        on_running=lambda item: None,
    )
    item = _item()
    manager.track(item)

    await _run_sweeper_briefly(manager, duration=0.12)

    assert gateway.record_retry_calls == [item.command_id]
    assert manager.is_tracked(item.command_id) is True


@pytest.mark.asyncio
async def test_sweep_retries_even_when_resend_raises_delivery_failed() -> None:
    """A DeliveryFailedError (backpressure) during a retry attempt still reschedules."""
    gateway = _FakeGateway()
    delivery = _FakeDelivery(raise_delivery_failed=True)
    manager = AckManager(
        gateway=gateway,  # type: ignore[arg-type]
        delivery=delivery,
        config=_config(max_retries=4, retry_backoff_base_seconds=0.3),
        on_running=lambda item: None,
    )
    item = _item()
    manager.track(item)

    await _run_sweeper_briefly(manager, duration=0.12)

    assert gateway.record_retry_calls == [item.command_id]
    assert manager.is_tracked(item.command_id) is True
