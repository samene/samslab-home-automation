"""The one contract every command handler implements.

The runtime (registry, executor, dispatcher) only ever calls through this
interface — it never knows a handler's own implementation, so a future
GPIO/camera/scheduler plugin only ever needs to register a new
``CommandHandler``, never change the runtime itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from app.commands.context import CommandContext

#: Used by a handler that doesn't override ``timeout()``.
DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[float] = 30.0


class CommandHandler(ABC):
    """Base class for one ``command_type``'s validation and execution logic.

    ``command_type``, ``validate()``, and ``execute()`` are the identity and
    behavior every handler must define. ``supports()`` and ``timeout()`` have
    sensible defaults and only need overriding when a handler's needs differ
    (e.g. a slow operation, or a handler matching more than one type).
    """

    @property
    @abstractmethod
    def command_type(self) -> str:
        """The dot-namespaced command type this handler is registered under (e.g. ``system.echo``)."""

    @abstractmethod
    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """Raise ``CommandValidationError`` if ``arguments`` are invalid for this command."""

    @abstractmethod
    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        """Perform the command and return its structured result data, if any."""

    def supports(self, command_type: str) -> bool:
        """Whether this handler can execute ``command_type``; defaults to an exact match."""
        return command_type == self.command_type

    def timeout(self) -> float:
        """Seconds the executor allows this command to run before timing it out."""
        return DEFAULT_COMMAND_TIMEOUT_SECONDS
