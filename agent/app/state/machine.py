"""The agent's lifecycle state machine: an explicit transition table plus a guard.

Follows the same pattern as the cloud server's command state machine
(``commands/service.py``'s ``ALLOWED_TRANSITIONS`` + ``ensure_transition_allowed``):
a plain ``dict[State, frozenset[State]]`` table and a single guard function that
every mutating call goes through first, rather than scattered if/elif checks.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Final

import structlog

from app.state.exceptions import InvalidStateTransitionError

logger = structlog.get_logger(__name__)


class AgentState(StrEnum):
    """Every lifecycle state the agent process can be in."""

    BOOTING = "BOOTING"
    INITIALIZING = "INITIALIZING"
    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


#: Allowed target states for each current state. STOPPING/STOPPED are reachable
#: from (almost) anywhere so shutdown is never blocked by an in-progress connect.
ALLOWED_TRANSITIONS: Final[dict[AgentState, frozenset[AgentState]]] = {
    AgentState.BOOTING: frozenset({AgentState.INITIALIZING, AgentState.STOPPING}),
    AgentState.INITIALIZING: frozenset({AgentState.CONNECTING, AgentState.STOPPING}),
    AgentState.CONNECTING: frozenset(
        {AgentState.AUTHENTICATING, AgentState.DISCONNECTED, AgentState.STOPPING}
    ),
    AgentState.AUTHENTICATING: frozenset(
        {AgentState.ONLINE, AgentState.DISCONNECTED, AgentState.STOPPING}
    ),
    AgentState.ONLINE: frozenset(
        {AgentState.DEGRADED, AgentState.DISCONNECTED, AgentState.STOPPING}
    ),
    AgentState.DEGRADED: frozenset(
        {AgentState.ONLINE, AgentState.DISCONNECTED, AgentState.STOPPING}
    ),
    AgentState.DISCONNECTED: frozenset({AgentState.CONNECTING, AgentState.STOPPING}),
    AgentState.STOPPING: frozenset({AgentState.STOPPED}),
    AgentState.STOPPED: frozenset(),
}

#: A listener is notified with (previous_state, new_state) after every successful transition.
StateChangeListener = Callable[[AgentState, AgentState], None]


def ensure_transition_allowed(current: AgentState, target: AgentState) -> None:
    """Raise ``InvalidStateTransitionError`` unless ``target`` is reachable from ``current``."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError(f"Cannot transition from {current} to {target}")


class StateMachine:
    """The agent's single source of truth for its own lifecycle state.

    Listeners are plain callables registered via ``add_listener`` — this is how
    other subsystems (metrics, health, plugins) observe state changes without
    the state machine importing any of them.
    """

    def __init__(self, *, initial: AgentState = AgentState.BOOTING) -> None:
        self._state = initial
        self._listeners: list[StateChangeListener] = []

    @property
    def state(self) -> AgentState:
        """The current lifecycle state."""
        return self._state

    def add_listener(self, listener: StateChangeListener) -> None:
        """Register a callable invoked with ``(previous, current)`` on every transition."""
        self._listeners.append(listener)

    def transition_to(self, target: AgentState) -> None:
        """Move to ``target``, raising if the transition isn't allowed from the current state."""
        ensure_transition_allowed(self._state, target)
        previous = self._state
        self._state = target
        logger.info("agent.state_transition", previous=previous, current=target)
        for listener in self._listeners:
            listener(previous, target)
