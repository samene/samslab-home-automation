"""Tests for CommandRegistry: register/unregister/find_handler/list_handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.commands.exceptions import DuplicateHandlerError, HandlerNotFoundError
from app.commands.handler import CommandHandler
from app.commands.metrics import REGISTERED_HANDLERS
from app.commands.registry import CommandRegistry


def _metric_value(metric: object) -> float:
    family = next(iter(metric.collect()))  # type: ignore[attr-defined]
    return float(family.samples[0].value)


class _EchoHandler(CommandHandler):
    def __init__(self, command_type: str = "test.echo") -> None:
        self._command_type = command_type

    @property
    def command_type(self) -> str:
        return self._command_type

    async def validate(self, context: Any, arguments: Mapping[str, Any]) -> None:
        pass

    async def execute(self, context: Any, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(arguments)


class _WildcardHandler(_EchoHandler):
    def __init__(self) -> None:
        super().__init__(command_type="test.wildcard_base")

    def supports(self, command_type: str) -> bool:
        return command_type.startswith("test.wildcard")


def test_registry_starts_empty() -> None:
    """A fresh registry has no handlers."""
    registry = CommandRegistry()
    assert registry.list_handlers() == ()


def test_register_adds_a_handler() -> None:
    """register() makes the handler findable by its command_type."""
    registry = CommandRegistry()
    handler = _EchoHandler()

    registry.register(handler)

    assert registry.find_handler("test.echo") is handler
    assert registry.list_handlers() == (handler,)


def test_register_updates_registered_handlers_gauge() -> None:
    """register()/unregister() set registered_handlers to this registry's own handler count.

    The gauge is a process-global singleton (by design — see
    ``app/commands/metrics.py``), so its value reflects whichever registry
    last called ``set()``; in production exactly one registry exists per
    process, so asserting the exact count (not a before/after delta) is what
    actually holds true here.
    """
    registry = CommandRegistry()

    registry.register(_EchoHandler("test.gauge_a"))
    assert _metric_value(REGISTERED_HANDLERS) == 1.0

    registry.register(_EchoHandler("test.gauge_b"))
    assert _metric_value(REGISTERED_HANDLERS) == 2.0

    registry.unregister("test.gauge_a")
    assert _metric_value(REGISTERED_HANDLERS) == 1.0


def test_register_rejects_duplicate_command_type() -> None:
    """Registering two handlers for the same command_type raises."""
    registry = CommandRegistry()
    registry.register(_EchoHandler())

    with pytest.raises(DuplicateHandlerError, match="test.echo"):
        registry.register(_EchoHandler())


def test_unregister_removes_a_handler() -> None:
    """unregister() makes the handler unfindable."""
    registry = CommandRegistry()
    registry.register(_EchoHandler())

    registry.unregister("test.echo")

    with pytest.raises(HandlerNotFoundError):
        registry.find_handler("test.echo")


def test_unregister_unknown_type_is_a_no_op() -> None:
    """unregister() for a type that was never registered doesn't raise."""
    registry = CommandRegistry()
    registry.unregister("test.never_registered")


def test_find_handler_raises_for_unknown_type() -> None:
    """find_handler() raises HandlerNotFoundError for an unregistered command_type."""
    registry = CommandRegistry()
    with pytest.raises(HandlerNotFoundError, match="test.missing"):
        registry.find_handler("test.missing")


def test_find_handler_falls_back_to_supports_for_a_wildcard_handler() -> None:
    """A handler registered under one key can still claim other types via supports()."""
    registry = CommandRegistry()
    wildcard = _WildcardHandler()
    registry.register(wildcard)

    assert registry.find_handler("test.wildcard_other") is wildcard


def test_list_handlers_preserves_registration_order() -> None:
    """list_handlers() returns handlers in the order they were registered."""
    registry = CommandRegistry()
    first = _EchoHandler("test.first")
    second = _EchoHandler("test.second")
    registry.register(first)
    registry.register(second)

    assert registry.list_handlers() == (first, second)
