"""Registers command handlers and looks them up by ``command_type``.

The one place the runtime maps a wire ``command_type`` string to a handler —
never a switch statement or ``if command_type == ...`` chain elsewhere. A
future plugin only ever needs to call ``register()`` with a new
``CommandHandler``; nothing here changes to support it.
"""

from __future__ import annotations

from app.commands.exceptions import DuplicateHandlerError, HandlerNotFoundError
from app.commands.handler import CommandHandler
from app.commands.metrics import REGISTERED_HANDLERS


class CommandRegistry:
    """Owns the set of registered command handlers, keyed by ``command_type``."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, handler: CommandHandler) -> None:
        """Register ``handler``; raises ``DuplicateHandlerError`` if its type is already taken."""
        if handler.command_type in self._handlers:
            raise DuplicateHandlerError(
                f"A handler is already registered for {handler.command_type!r}"
            )
        self._handlers[handler.command_type] = handler
        REGISTERED_HANDLERS.set(len(self._handlers))

    def unregister(self, command_type: str) -> None:
        """Remove the handler registered for ``command_type``; a no-op if none is registered."""
        self._handlers.pop(command_type, None)
        REGISTERED_HANDLERS.set(len(self._handlers))

    def find_handler(self, command_type: str) -> CommandHandler:
        """Return the handler for ``command_type``, raising ``HandlerNotFoundError`` if none matches.

        An exact match on the registration key is tried first (the common
        case, O(1)); a handler registered under a different key can still
        claim a type through its own ``supports()`` override.
        """
        handler = self._handlers.get(command_type)
        if handler is not None:
            return handler
        for candidate in self._handlers.values():
            if candidate.supports(command_type):
                return candidate
        raise HandlerNotFoundError(f"No handler registered for {command_type!r}")

    def list_handlers(self) -> tuple[CommandHandler, ...]:
        """Every registered handler, in registration order."""
        return tuple(self._handlers.values())
