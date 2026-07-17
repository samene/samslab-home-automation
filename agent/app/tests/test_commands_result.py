"""Tests for the CommandResult model and its exit-code conventions."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.commands.result import (
    EXIT_CODE_CANCELLED,
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_TIMEOUT,
    CommandResult,
    CommandResultStatus,
)


def test_exit_code_conventions() -> None:
    """Exit codes follow the documented shell conventions."""
    assert EXIT_CODE_SUCCESS == 0
    assert EXIT_CODE_FAILURE == 1
    assert EXIT_CODE_TIMEOUT == 124
    assert EXIT_CODE_CANCELLED == 130


def test_command_result_defaults() -> None:
    """A minimal CommandResult defaults to success-shaped fields."""
    command_id = uuid4()
    result = CommandResult(
        command_id=command_id, status=CommandResultStatus.SUCCESS, duration_seconds=0.01
    )
    assert result.command_id == command_id
    assert result.result is None
    assert result.error_message is None
    assert result.stack_trace is None
    assert result.exit_code == EXIT_CODE_SUCCESS


def test_command_result_is_immutable() -> None:
    """CommandResult is a frozen dataclass."""
    result = CommandResult(
        command_id=uuid4(), status=CommandResultStatus.SUCCESS, duration_seconds=0.0
    )
    with pytest.raises(AttributeError):
        result.status = CommandResultStatus.FAILED  # type: ignore[misc]


def test_command_result_status_values() -> None:
    """Every documented terminal status exists."""
    assert {status.value for status in CommandResultStatus} == {
        "SUCCESS",
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
    }
