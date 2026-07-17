"""Tests for ResultHandler: completing/failing tracked commands and dropping duplicates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.events.domain_events import CommandResultReceived
from app.dispatcher.config import DispatcherConfig
from app.dispatcher.queue import QueuedCommand
from app.dispatcher.result_handler import ResultHandler
from app.dispatcher.timeouts import TimeoutMonitor
from app.domains.commands.models import CommandPriority


class _FakeGateway:
    def __init__(self) -> None:
        self.complete_calls: list[tuple[object, dict[str, object]]] = []
        self.fail_calls: list[tuple[object, str]] = []

    async def complete_command(self, command_id: object, *, result: dict[str, object]) -> object:
        self.complete_calls.append((command_id, result))
        return object()

    async def fail_command(self, command_id: object, *, error_message: str) -> object:
        self.fail_calls.append((command_id, error_message))
        return object()

    async def mark_timeout(self, command_id: object) -> object:
        raise AssertionError("ResultHandler should never call mark_timeout")


def _config() -> DispatcherConfig:
    return DispatcherConfig(
        poll_interval_seconds=1.0,
        discovery_batch_size=100,
        ack_timeout_seconds=10.0,
        execution_timeout_seconds=60.0,
        max_retries=4,
        retry_backoff_base_seconds=1.0,
        retry_backoff_max_seconds=30.0,
        sweep_interval_seconds=1.0,
    )


def _item() -> QueuedCommand:
    return QueuedCommand(
        command_id=uuid4(),
        device_id=uuid4(),
        priority=CommandPriority.NORMAL,
        command_type="pump.start",
        payload={},
        enqueued_at=datetime.now(UTC),
    )


def _result_event(
    item: QueuedCommand, *, success: bool, **overrides: object
) -> CommandResultReceived:
    fields: dict[str, object] = {
        "command_id": item.command_id,
        "device_id": item.device_id,
        "success": success,
        "result": {"ok": True} if success else {},
        "error_message": None if success else "boom",
        "occurred_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return CommandResultReceived(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_successful_result_completes_a_tracked_command() -> None:
    """A tracked, successful result calls complete_command with the reported result."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    handler = ResultHandler(gateway=gateway, timeout_monitor=monitor)  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)

    await handler.handle_result(_result_event(item, success=True))

    assert gateway.complete_calls == [(item.command_id, {"ok": True})]
    assert gateway.fail_calls == []
    assert monitor.is_tracked(item.command_id) is False


@pytest.mark.asyncio
async def test_a_failed_result_fails_a_tracked_command() -> None:
    """A tracked, unsuccessful result calls fail_command with the reported error."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    handler = ResultHandler(gateway=gateway, timeout_monitor=monitor)  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)

    await handler.handle_result(_result_event(item, success=False))

    assert gateway.fail_calls == [(item.command_id, "boom")]
    assert gateway.complete_calls == []


@pytest.mark.asyncio
async def test_a_failed_result_with_no_error_message_uses_a_default() -> None:
    """A failure result missing an error_message still fails with a safe default."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    handler = ResultHandler(gateway=gateway, timeout_monitor=monitor)  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)

    await handler.handle_result(_result_event(item, success=False, error_message=None))

    assert gateway.fail_calls == [(item.command_id, "Command failed")]


@pytest.mark.asyncio
async def test_a_duplicate_or_unknown_result_is_dropped_not_fatal() -> None:
    """A result for a command not currently tracked (already handled) is ignored."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    handler = ResultHandler(gateway=gateway, timeout_monitor=monitor)  # type: ignore[arg-type]
    item = _item()
    # Never tracked at all (e.g. a resend/duplicate the agent produced).

    await handler.handle_result(_result_event(item, success=True))

    assert gateway.complete_calls == []
    assert gateway.fail_calls == []


@pytest.mark.asyncio
async def test_a_second_result_for_an_already_resolved_command_is_dropped() -> None:
    """A second COMMAND_RESULT for a command already completed is a no-op, not a re-completion."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    handler = ResultHandler(gateway=gateway, timeout_monitor=monitor)  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)

    await handler.handle_result(_result_event(item, success=True))
    await handler.handle_result(_result_event(item, success=True))

    assert gateway.complete_calls == [(item.command_id, {"ok": True})]
