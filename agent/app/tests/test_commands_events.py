"""Tests for the command event bus."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.commands.events import CommandEvent, CommandEventBus
from app.commands.lifecycle import CommandLifecycleState


def _event(state: CommandLifecycleState) -> CommandEvent:
    return CommandEvent(
        state=state, command_id=uuid4(), command_type="test.echo", occurred_at=datetime.now(UTC)
    )


def test_publish_calls_every_subscriber_for_that_state() -> None:
    """publish() invokes every listener registered for the event's state."""
    bus = CommandEventBus()
    received: list[CommandEvent] = []
    bus.subscribe(CommandLifecycleState.RUNNING, received.append)

    event = _event(CommandLifecycleState.RUNNING)
    bus.publish(event)

    assert received == [event]


def test_publish_does_not_call_listeners_for_other_states() -> None:
    """A listener registered for one state is never called for another."""
    bus = CommandEventBus()
    received: list[CommandEvent] = []
    bus.subscribe(CommandLifecycleState.RUNNING, received.append)

    bus.publish(_event(CommandLifecycleState.COMPLETED))

    assert received == []


def test_publish_with_no_subscribers_does_not_raise() -> None:
    """Publishing an event nobody is listening for is a no-op."""
    bus = CommandEventBus()
    bus.publish(_event(CommandLifecycleState.FAILED))


def test_unsubscribe_removes_a_listener() -> None:
    """unsubscribe() stops a listener from being called."""
    bus = CommandEventBus()
    received: list[CommandEvent] = []
    bus.subscribe(CommandLifecycleState.RUNNING, received.append)

    bus.unsubscribe(CommandLifecycleState.RUNNING, received.append)
    bus.publish(_event(CommandLifecycleState.RUNNING))

    assert received == []


def test_unsubscribe_unknown_listener_is_a_no_op() -> None:
    """unsubscribe() for a listener that was never registered doesn't raise."""
    bus = CommandEventBus()
    bus.unsubscribe(CommandLifecycleState.RUNNING, lambda event: None)


def test_multiple_subscribers_are_all_called_in_order() -> None:
    """Multiple listeners for the same state are all invoked, in registration order."""
    bus = CommandEventBus()
    order: list[str] = []
    bus.subscribe(CommandLifecycleState.RUNNING, lambda event: order.append("first"))
    bus.subscribe(CommandLifecycleState.RUNNING, lambda event: order.append("second"))

    bus.publish(_event(CommandLifecycleState.RUNNING))

    assert order == ["first", "second"]
