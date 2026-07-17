"""Tests for the CommandHandler base class contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.commands.handler import DEFAULT_COMMAND_TIMEOUT_SECONDS, CommandHandler


def test_command_handler_cannot_be_instantiated_directly() -> None:
    """CommandHandler is a true ABC — command_type/validate/execute are mandatory."""
    with pytest.raises(TypeError):
        CommandHandler()  # type: ignore[abstract]


class _MinimalHandler(CommandHandler):
    @property
    def command_type(self) -> str:
        return "test.minimal"

    async def validate(self, context: Any, arguments: Mapping[str, Any]) -> None:
        """Accepts anything."""

    async def execute(self, context: Any, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(arguments)


def test_default_timeout_is_the_documented_constant() -> None:
    """A handler that doesn't override timeout() gets the default."""
    handler = _MinimalHandler()
    assert handler.timeout() == DEFAULT_COMMAND_TIMEOUT_SECONDS


def test_default_supports_matches_only_the_handlers_own_command_type() -> None:
    """The default supports() is an exact match on command_type."""
    handler = _MinimalHandler()
    assert handler.supports("test.minimal") is True
    assert handler.supports("test.other") is False


class _CustomTimeoutHandler(_MinimalHandler):
    def timeout(self) -> float:
        return 5.0


def test_timeout_is_overridable() -> None:
    """A handler may override timeout() with its own value."""
    assert _CustomTimeoutHandler().timeout() == 5.0


class _WildcardHandler(_MinimalHandler):
    @property
    def command_type(self) -> str:
        return "test.wildcard_base"

    def supports(self, command_type: str) -> bool:
        return command_type.startswith("test.wildcard")


def test_supports_is_overridable_for_pattern_matching() -> None:
    """A handler may override supports() to match more than one command_type."""
    handler = _WildcardHandler()
    assert handler.supports("test.wildcard_base") is True
    assert handler.supports("test.wildcard_other") is True
    assert handler.supports("test.unrelated") is False


@pytest.mark.asyncio
async def test_minimal_handler_executes() -> None:
    """A concrete handler's execute() runs and returns its result."""
    handler = _MinimalHandler()
    result = await handler.execute(None, {"a": 1})
    assert result == {"a": 1}
