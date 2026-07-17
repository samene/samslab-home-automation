"""Exhaustive tests for the agent's lifecycle state machine."""

from __future__ import annotations

from itertools import product

import pytest

from app.state.exceptions import InvalidStateTransitionError
from app.state.machine import (
    ALLOWED_TRANSITIONS,
    AgentState,
    StateMachine,
    ensure_transition_allowed,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [(c, t) for c, t in product(AgentState, AgentState) if t in ALLOWED_TRANSITIONS[c]],
)
def test_every_allowed_transition_succeeds(current: AgentState, target: AgentState) -> None:
    """Every (current, target) pair listed as allowed does not raise."""
    ensure_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [(c, t) for c, t in product(AgentState, AgentState) if t not in ALLOWED_TRANSITIONS[c]],
)
def test_every_disallowed_transition_raises(current: AgentState, target: AgentState) -> None:
    """Every (current, target) pair not listed as allowed raises."""
    with pytest.raises(InvalidStateTransitionError):
        ensure_transition_allowed(current, target)


def test_stopped_is_terminal() -> None:
    """STOPPED has no allowed outbound transitions."""
    assert ALLOWED_TRANSITIONS[AgentState.STOPPED] == frozenset()


def test_state_machine_starts_booting() -> None:
    """A fresh state machine defaults to BOOTING."""
    machine = StateMachine()
    assert machine.state is AgentState.BOOTING


def test_state_machine_accepts_custom_initial_state() -> None:
    """An explicit initial state is honored."""
    machine = StateMachine(initial=AgentState.ONLINE)
    assert machine.state is AgentState.ONLINE


def test_state_machine_transitions_and_updates_state() -> None:
    """A successful transition updates ``state``."""
    machine = StateMachine()
    machine.transition_to(AgentState.INITIALIZING)
    assert machine.state is AgentState.INITIALIZING


def test_state_machine_rejects_invalid_transition() -> None:
    """An invalid transition raises and leaves the state unchanged."""
    machine = StateMachine()
    with pytest.raises(InvalidStateTransitionError):
        machine.transition_to(AgentState.ONLINE)
    assert machine.state is AgentState.BOOTING


def test_state_machine_notifies_listeners() -> None:
    """Registered listeners are called with (previous, current) on every transition."""
    machine = StateMachine()
    observed: list[tuple[AgentState, AgentState]] = []
    machine.add_listener(lambda previous, current: observed.append((previous, current)))

    machine.transition_to(AgentState.INITIALIZING)

    assert observed == [(AgentState.BOOTING, AgentState.INITIALIZING)]


def test_state_machine_does_not_notify_listeners_on_rejected_transition() -> None:
    """A rejected transition never invokes listeners."""
    machine = StateMachine()
    observed: list[tuple[AgentState, AgentState]] = []
    machine.add_listener(lambda previous, current: observed.append((previous, current)))

    with pytest.raises(InvalidStateTransitionError):
        machine.transition_to(AgentState.ONLINE)

    assert observed == []
