"""Tests for TimeoutMonitor: execution-timeout tracking and sweeping."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.dispatcher.config import DispatcherConfig
from app.dispatcher.queue import QueuedCommand
from app.dispatcher.timeouts import TimeoutMonitor
from app.domains.commands.models import CommandPriority


class _FakeGateway:
    def __init__(self) -> None:
        self.mark_timeout_calls: list[object] = []

    async def mark_timeout(self, command_id: object) -> object:
        self.mark_timeout_calls.append(command_id)
        return object()


def _config(**overrides: Any) -> DispatcherConfig:
    base: dict[str, Any] = dict(
        poll_interval_seconds=1.0,
        discovery_batch_size=100,
        ack_timeout_seconds=10.0,
        execution_timeout_seconds=0.03,
        max_retries=4,
        retry_backoff_base_seconds=1.0,
        retry_backoff_max_seconds=30.0,
        sweep_interval_seconds=0.02,
    )
    base.update(overrides)
    return DispatcherConfig(**base)


def _item() -> QueuedCommand:
    return QueuedCommand(
        command_id=uuid4(),
        device_id=uuid4(),
        priority=CommandPriority.NORMAL,
        command_type="pump.start",
        payload={},
        enqueued_at=datetime.now(UTC),
    )


def test_track_marks_a_command_as_running() -> None:
    """A tracked command is reported as tracked until resolved or timed out."""
    monitor = TimeoutMonitor(gateway=_FakeGateway(), config=_config())  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)
    assert monitor.is_tracked(item.command_id) is True
    assert monitor.snapshot() == [item]


def test_resolve_stops_tracking_and_returns_the_item() -> None:
    """Resolving a tracked command removes it and returns the original item."""
    monitor = TimeoutMonitor(gateway=_FakeGateway(), config=_config())  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)
    resolved = monitor.resolve(item.command_id)
    assert resolved is item
    assert monitor.is_tracked(item.command_id) is False


def test_resolve_an_untracked_command_returns_none() -> None:
    """Resolving a command never tracked here (duplicate/unknown result) is safe."""
    monitor = TimeoutMonitor(gateway=_FakeGateway(), config=_config())  # type: ignore[arg-type]
    assert monitor.resolve(uuid4()) is None


@pytest.mark.asyncio
async def test_sweep_times_out_a_command_that_never_gets_a_result() -> None:
    """A command whose execution window elapses is marked TIMEOUT and untracked."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert monitor.is_tracked(item.command_id) is False
    assert gateway.mark_timeout_calls == [item.command_id]


@pytest.mark.asyncio
async def test_a_command_resolved_before_its_deadline_never_times_out() -> None:
    """Resolving a command (its result arrived) prevents the sweep from timing it out."""
    gateway = _FakeGateway()
    monitor = TimeoutMonitor(gateway=gateway, config=_config())  # type: ignore[arg-type]
    item = _item()
    monitor.track(item)
    monitor.resolve(item.command_id)

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert gateway.mark_timeout_calls == []
