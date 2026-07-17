"""A lightweight, in-process, synchronous publish/subscribe bus for command lifecycle events.

Scoped to the commands package only — mirrors the shape of the cloud server's
own ``EventBus`` (``server/app/application/events/``: subscribe/publish/
unsubscribe, in-process only) but is its own instance here, since the command
runtime is transport-independent and must not reach for anything server-side.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.commands.lifecycle import CommandLifecycleState


@dataclass(frozen=True)
class CommandEvent:
    """One command lifecycle transition, published for anything that wants to observe it."""

    state: CommandLifecycleState
    command_id: UUID
    command_type: str
    occurred_at: datetime
    detail: Mapping[str, Any] = field(default_factory=dict)


CommandEventListener = Callable[[CommandEvent], None]


class CommandEventBus:
    """Synchronous pub/sub keyed by lifecycle state; listeners are expected to be fast (non-blocking)."""

    def __init__(self) -> None:
        self._listeners: dict[CommandLifecycleState, list[CommandEventListener]] = defaultdict(list)

    def subscribe(self, state: CommandLifecycleState, listener: CommandEventListener) -> None:
        """Register ``listener`` to be called whenever a command reaches ``state``."""
        self._listeners[state].append(listener)

    def unsubscribe(self, state: CommandLifecycleState, listener: CommandEventListener) -> None:
        """Remove a previously registered listener; a no-op if it isn't registered."""
        listeners = self._listeners.get(state)
        if listeners is not None and listener in listeners:
            listeners.remove(listener)

    def publish(self, event: CommandEvent) -> None:
        """Call every listener registered for ``event.state``, in registration order."""
        for listener in self._listeners.get(event.state, []):
            listener(event)
