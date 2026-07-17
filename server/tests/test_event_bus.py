"""Tests for the in-process application event bus."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    CommandCompleted,
    CommandCreated,
    CommandFailed,
    DeviceHeartbeat,
    DeviceRegistered,
)
from app.application.events.logging_subscriber import register_logging_subscriber


@dataclass(frozen=True, slots=True)
class _SampleEvent:
    """A minimal event used only to exercise the bus in isolation."""

    value: int


@dataclass(frozen=True, slots=True)
class _OtherEvent:
    """A distinct event type used to prove type-based routing."""

    value: int


@pytest.mark.asyncio
async def test_event_bus_calls_a_synchronous_subscriber() -> None:
    """A plain sync handler is called with the published event."""
    bus = EventBus()
    received: list[_SampleEvent] = []
    bus.subscribe(_SampleEvent, received.append)

    await bus.publish(_SampleEvent(value=1))

    assert received == [_SampleEvent(value=1)]


@pytest.mark.asyncio
async def test_event_bus_calls_an_asynchronous_subscriber() -> None:
    """An async handler is awaited before publish() returns."""
    bus = EventBus()
    received: list[_SampleEvent] = []

    async def handler(event: _SampleEvent) -> None:
        received.append(event)

    bus.subscribe(_SampleEvent, handler)
    await bus.publish(_SampleEvent(value=42))

    assert received == [_SampleEvent(value=42)]


@pytest.mark.asyncio
async def test_event_bus_calls_every_subscriber_in_order() -> None:
    """Multiple subscribers to the same event type are all called."""
    bus = EventBus()
    calls: list[str] = []
    bus.subscribe(_SampleEvent, lambda event: calls.append("first"))
    bus.subscribe(_SampleEvent, lambda event: calls.append("second"))

    await bus.publish(_SampleEvent(value=1))

    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_event_bus_only_calls_subscribers_of_the_exact_event_type() -> None:
    """A subscriber to one event type never receives a different event type."""
    bus = EventBus()
    sample_received: list[_SampleEvent] = []
    other_received: list[_OtherEvent] = []
    bus.subscribe(_SampleEvent, sample_received.append)
    bus.subscribe(_OtherEvent, other_received.append)

    await bus.publish(_SampleEvent(value=1))

    assert sample_received == [_SampleEvent(value=1)]
    assert other_received == []


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_stops_future_calls() -> None:
    """After unsubscribing, a handler no longer receives events."""
    bus = EventBus()
    received: list[_SampleEvent] = []

    def handler(event: _SampleEvent) -> None:
        received.append(event)

    bus.subscribe(_SampleEvent, handler)
    bus.unsubscribe(_SampleEvent, handler)
    await bus.publish(_SampleEvent(value=1))

    assert received == []


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_is_a_no_op_for_an_unknown_handler() -> None:
    """Unsubscribing a handler that was never subscribed does not raise."""
    bus = EventBus()

    def handler(event: _SampleEvent) -> None:
        raise AssertionError("should never be called")

    bus.unsubscribe(_SampleEvent, handler)  # no prior subscribe() for this event type at all


@pytest.mark.asyncio
async def test_event_bus_publish_with_no_subscribers_does_not_raise() -> None:
    """Publishing an event nobody subscribed to is a safe no-op."""
    bus = EventBus()
    await bus.publish(_SampleEvent(value=1))


@pytest.mark.asyncio
async def test_logging_subscriber_handles_every_known_domain_event() -> None:
    """The reference logging subscriber can be wired to, and receive, every domain event."""
    bus = EventBus()
    register_logging_subscriber(bus)

    now = datetime.now(UTC)
    await bus.publish(
        DeviceRegistered(device_id=uuid4(), device_name="garden-node", occurred_at=now)
    )
    await bus.publish(DeviceHeartbeat(device_id=uuid4(), status="ONLINE", occurred_at=now))
    await bus.publish(
        CommandCreated(
            command_id=uuid4(), device_id=uuid4(), command_type="pump.start", occurred_at=now
        )
    )
    await bus.publish(CommandCompleted(command_id=uuid4(), device_id=uuid4(), occurred_at=now))
    await bus.publish(
        CommandFailed(command_id=uuid4(), device_id=uuid4(), error_message="boom", occurred_at=now)
    )
