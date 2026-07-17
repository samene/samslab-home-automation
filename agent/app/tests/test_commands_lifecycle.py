"""Exhaustive tests for the command lifecycle state machine."""

from __future__ import annotations

from itertools import product
from uuid import uuid4

import pytest

from app.commands.events import CommandEvent, CommandEventBus
from app.commands.exceptions import InvalidLifecycleTransitionError
from app.commands.lifecycle import (
    ALLOWED_TRANSITIONS,
    RESULT_STATUS_TO_LIFECYCLE_STATE,
    CommandLifecycle,
    CommandLifecycleState,
    ensure_transition_allowed,
)
from app.commands.result import CommandResultStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (c, t)
        for c, t in product(CommandLifecycleState, CommandLifecycleState)
        if t in ALLOWED_TRANSITIONS[c]
    ],
)
def test_every_allowed_transition_succeeds(
    current: CommandLifecycleState, target: CommandLifecycleState
) -> None:
    """Every (current, target) pair listed as allowed does not raise."""
    ensure_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (c, t)
        for c, t in product(CommandLifecycleState, CommandLifecycleState)
        if t not in ALLOWED_TRANSITIONS[c]
    ],
)
def test_every_disallowed_transition_raises(
    current: CommandLifecycleState, target: CommandLifecycleState
) -> None:
    """Every (current, target) pair not listed as allowed raises."""
    with pytest.raises(InvalidLifecycleTransitionError):
        ensure_transition_allowed(current, target)


@pytest.mark.parametrize(
    "state",
    [
        CommandLifecycleState.COMPLETED,
        CommandLifecycleState.FAILED,
        CommandLifecycleState.CANCELLED,
        CommandLifecycleState.TIMEOUT,
    ],
)
def test_terminal_states_have_no_outbound_transitions(state: CommandLifecycleState) -> None:
    """Every terminal state is truly terminal."""
    assert ALLOWED_TRANSITIONS[state] == frozenset()


def test_result_status_to_lifecycle_state_covers_every_status() -> None:
    """Every CommandResultStatus maps to exactly one terminal lifecycle state."""
    assert set(RESULT_STATUS_TO_LIFECYCLE_STATE) == set(CommandResultStatus)
    for state in RESULT_STATUS_TO_LIFECYCLE_STATE.values():
        assert ALLOWED_TRANSITIONS[state] == frozenset()


def test_lifecycle_starts_received() -> None:
    """A fresh CommandLifecycle defaults to RECEIVED."""
    lifecycle = CommandLifecycle(
        command_id=uuid4(), command_type="test.echo", event_bus=CommandEventBus()
    )
    assert lifecycle.state is CommandLifecycleState.RECEIVED


def test_transition_to_updates_state_and_publishes_event() -> None:
    """A successful transition updates state and publishes a CommandEvent."""
    bus = CommandEventBus()
    received: list[CommandEvent] = []
    bus.subscribe(CommandLifecycleState.VALIDATED, received.append)
    command_id = uuid4()
    lifecycle = CommandLifecycle(command_id=command_id, command_type="test.echo", event_bus=bus)

    lifecycle.transition_to(CommandLifecycleState.VALIDATED, detail={"note": "ok"})

    assert lifecycle.state is CommandLifecycleState.VALIDATED
    assert len(received) == 1
    assert received[0].command_id == command_id
    assert received[0].command_type == "test.echo"
    assert received[0].detail == {"note": "ok"}


def test_transition_to_raises_and_does_not_publish_on_invalid_transition() -> None:
    """An invalid transition raises and never reaches the event bus."""
    bus = CommandEventBus()
    received: list[CommandEvent] = []
    bus.subscribe(CommandLifecycleState.RUNNING, received.append)
    lifecycle = CommandLifecycle(command_id=uuid4(), command_type="test.echo", event_bus=bus)

    with pytest.raises(InvalidLifecycleTransitionError):
        lifecycle.transition_to(CommandLifecycleState.RUNNING)

    assert received == []
    assert lifecycle.state is CommandLifecycleState.RECEIVED
