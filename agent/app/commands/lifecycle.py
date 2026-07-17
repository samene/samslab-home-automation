"""One command's lifecycle: an explicit transition table plus a guard, exactly

like the cloud server's own command state machine
(``server/app/domains/commands/service.py``'s ``ALLOWED_TRANSITIONS`` +
``ensure_transition_allowed``) — a plain ``dict[State, frozenset[State]]``
table, not scattered if/elif checks. Every transition publishes a
``CommandEvent`` on the shared ``CommandEventBus``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from app.commands.events import CommandEvent, CommandEventBus
from app.commands.exceptions import InvalidLifecycleTransitionError
from app.commands.result import CommandResultStatus


class CommandLifecycleState(StrEnum):
    """Every stage one command's execution passes through."""

    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


#: RECEIVED -> VALIDATED -> ACKNOWLEDGED -> RUNNING -> one terminal state.
#: FAILED is reachable earlier too (a lookup or validation failure never
#: reaches ACKNOWLEDGED/RUNNING at all).
ALLOWED_TRANSITIONS: Final[dict[CommandLifecycleState, frozenset[CommandLifecycleState]]] = {
    CommandLifecycleState.RECEIVED: frozenset(
        {CommandLifecycleState.VALIDATED, CommandLifecycleState.FAILED}
    ),
    CommandLifecycleState.VALIDATED: frozenset(
        {CommandLifecycleState.ACKNOWLEDGED, CommandLifecycleState.FAILED}
    ),
    CommandLifecycleState.ACKNOWLEDGED: frozenset(
        {CommandLifecycleState.RUNNING, CommandLifecycleState.FAILED}
    ),
    CommandLifecycleState.RUNNING: frozenset(
        {
            CommandLifecycleState.COMPLETED,
            CommandLifecycleState.FAILED,
            CommandLifecycleState.CANCELLED,
            CommandLifecycleState.TIMEOUT,
        }
    ),
    CommandLifecycleState.COMPLETED: frozenset(),
    CommandLifecycleState.FAILED: frozenset(),
    CommandLifecycleState.CANCELLED: frozenset(),
    CommandLifecycleState.TIMEOUT: frozenset(),
}

#: How a terminal ``CommandResultStatus`` maps onto a terminal lifecycle state.
RESULT_STATUS_TO_LIFECYCLE_STATE: Final[dict[CommandResultStatus, CommandLifecycleState]] = {
    CommandResultStatus.SUCCESS: CommandLifecycleState.COMPLETED,
    CommandResultStatus.FAILED: CommandLifecycleState.FAILED,
    CommandResultStatus.CANCELLED: CommandLifecycleState.CANCELLED,
    CommandResultStatus.TIMEOUT: CommandLifecycleState.TIMEOUT,
}


def ensure_transition_allowed(
    current: CommandLifecycleState, target: CommandLifecycleState
) -> None:
    """Raise ``InvalidLifecycleTransitionError`` unless ``target`` is reachable from ``current``."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(f"Cannot transition from {current} to {target}")


class CommandLifecycle:
    """Tracks one command's lifecycle state and publishes an event on every transition."""

    def __init__(
        self,
        *,
        command_id: UUID,
        command_type: str,
        event_bus: CommandEventBus,
        initial: CommandLifecycleState = CommandLifecycleState.RECEIVED,
    ) -> None:
        self._command_id = command_id
        self._command_type = command_type
        self._event_bus = event_bus
        self._state = initial

    @property
    def state(self) -> CommandLifecycleState:
        """The command's current lifecycle state."""
        return self._state

    def transition_to(
        self, target: CommandLifecycleState, *, detail: Mapping[str, Any] | None = None
    ) -> None:
        """Move to ``target``, raising if not allowed, then publish the transition as an event."""
        ensure_transition_allowed(self._state, target)
        self._state = target
        self._event_bus.publish(
            CommandEvent(
                state=target,
                command_id=self._command_id,
                command_type=self._command_type,
                occurred_at=datetime.now(UTC),
                detail=detail or {},
            )
        )
