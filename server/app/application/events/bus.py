"""A lightweight in-process publish/subscribe event bus.

No external messaging (no broker, no queue). Handlers may be sync or async.
One ``EventBus`` instance is shared for the lifetime of one application
(see ``app.core.container.ApplicationContainer``), so a handler subscribed at
startup keeps receiving events for every request.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any, TypeVar

T = TypeVar("T")
EventHandler = Callable[[T], "Awaitable[None] | None"]


class EventBus:
    """Route published events to every handler subscribed to that event's exact type."""

    def __init__(self) -> None:
        """Start with no subscribers; each application instance owns its own bus."""
        self._subscribers: dict[type, list[EventHandler[Any]]] = defaultdict(list)

    def subscribe(self, event_type: type[T], handler: EventHandler[T]) -> None:
        """Register ``handler`` to be called with every future ``event_type`` event."""
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type[T], handler: EventHandler[T]) -> None:
        """Stop calling ``handler`` for ``event_type``; a no-op if it wasn't subscribed."""
        handlers = self._subscribers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Any) -> None:
        """Call every handler subscribed to ``event``'s exact type, in subscription order."""
        for handler in list(self._subscribers.get(type(event), ())):
            result = handler(event)
            if isawaitable(result):
                await result
