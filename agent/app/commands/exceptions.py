"""Failures raised by the command runtime; never a transport or domain exception.

None of these ever escape ``CommandDispatcher.handle_command`` — the transport
layer (the WebSocket connection, the receive loop) must never see one.
"""

from __future__ import annotations


class CommandRuntimeError(Exception):
    """Base error for every command-runtime failure."""


class DuplicateHandlerError(CommandRuntimeError):
    """Raised when ``CommandRegistry.register`` is called for an already-registered command_type."""


class HandlerNotFoundError(CommandRuntimeError):
    """Raised when no registered handler supports a given command_type."""


class CommandValidationError(CommandRuntimeError):
    """Raised by a handler's ``validate()`` when the command's arguments are invalid."""


class InvalidLifecycleTransitionError(CommandRuntimeError):
    """Raised when a lifecycle transition isn't in the current state's allowed target set."""
