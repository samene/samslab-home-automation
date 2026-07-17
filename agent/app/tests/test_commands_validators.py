"""Tests for reusable command validation helpers."""

from __future__ import annotations

import pytest

from app.commands.exceptions import CommandValidationError
from app.commands.validators import (
    require_keys,
    require_type,
    validate_command_type_format,
)


@pytest.mark.parametrize("command_type", ["system.echo", "system.ping", "gpio.pump_start", "a.b.c"])
def test_validate_command_type_format_accepts_well_formed_types(command_type: str) -> None:
    """A lowercase, dot-namespaced command_type is accepted."""
    validate_command_type_format(command_type)


@pytest.mark.parametrize(
    "command_type", ["", "System.Echo", "system", "system..echo", "system.echo!", "1system.echo"]
)
def test_validate_command_type_format_rejects_malformed_types(command_type: str) -> None:
    """A malformed command_type raises CommandValidationError."""
    with pytest.raises(CommandValidationError, match="Malformed command_type"):
        validate_command_type_format(command_type)


def test_require_keys_passes_when_all_present() -> None:
    """require_keys() doesn't raise when every key is present."""
    require_keys({"a": 1, "b": 2}, "a", "b")


def test_require_keys_raises_when_missing() -> None:
    """require_keys() raises naming every missing key."""
    with pytest.raises(CommandValidationError, match="b, c"):
        require_keys({"a": 1}, "a", "b", "c")


def test_require_type_passes_for_matching_type() -> None:
    """require_type() doesn't raise when the value matches the expected type."""
    require_type({"count": 5}, "count", int)


def test_require_type_raises_for_mismatched_type() -> None:
    """require_type() raises naming the expected and actual types."""
    with pytest.raises(CommandValidationError, match="must be of type int, got str"):
        require_type({"count": "five"}, "count", int)
