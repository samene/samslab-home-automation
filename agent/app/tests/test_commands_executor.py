"""Tests for CommandExecutor: timeouts, cancellation, retries, and metrics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.commands import metrics as command_metrics
from app.commands.context import CommandContext, CommandServices
from app.commands.executor import CommandExecutor, ExecutorConfig
from app.commands.handler import CommandHandler
from app.commands.metrics import (
    COMMAND_EXECUTION_DURATION_SECONDS,
    COMMANDS_COMPLETED_TOTAL,
    COMMANDS_FAILED_TOTAL,
    COMMANDS_TIMEOUT_TOTAL,
)
from app.commands.registry import CommandRegistry
from app.commands.result import (
    EXIT_CODE_CANCELLED,
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_TIMEOUT,
    CommandResultStatus,
)
from app.health.service import HealthService
from app.plugins.camera.service import CameraService
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings


def _metric_value(metric: Any, **labels: str) -> float:
    target = metric.labels(**labels) if labels else metric
    return float(next(iter(target.collect())).samples[0].value)


def _make_context(
    *, command_id: UUID | None = None, command_type: str = "test.scripted", debug: bool = False
) -> CommandContext:
    settings = make_settings(DEBUG=debug)
    plugin_manager = PluginManager()
    session = SessionState()
    services = CommandServices(
        plugin_manager=plugin_manager,
        health_service=HealthService(
            settings=settings, session=session, plugin_manager=plugin_manager
        ),
        registry=CommandRegistry(),
        agent_started_at=datetime.now(UTC),
        camera_service=CameraService(settings),
        pump_service=PumpService(settings),
    )
    return CommandContext(
        command_id=command_id or uuid4(),
        command_type=command_type,
        correlation_id=None,
        trace_id=None,
        device_name=settings.device_name,
        device_display_name=None,
        agent_version="0.1.0",
        settings=settings,
        logger=None,
        metrics=command_metrics,
        services=services,
    )


Behavior = Callable[[int, CommandContext, Mapping[str, Any]], Awaitable[Mapping[str, Any] | None]]


class _ScriptedHandler(CommandHandler):
    """A handler whose execute() delegates to a test-supplied async callable."""

    def __init__(
        self,
        *,
        behavior: Behavior,
        command_type: str = "test.scripted",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._behavior = behavior
        self._command_type = command_type
        self._timeout_seconds = timeout_seconds
        self.calls = 0

    @property
    def command_type(self) -> str:
        return self._command_type

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        pass

    def timeout(self) -> float:
        return self._timeout_seconds

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        self.calls += 1
        return await self._behavior(self.calls, context, arguments)


@pytest.mark.asyncio
async def test_successful_execution_returns_success_result_with_data() -> None:
    """A handler that returns data produces a SUCCESS result carrying that data."""

    async def behavior(
        call: int, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return {"echoed": arguments}

    handler = _ScriptedHandler(behavior=behavior)
    context = _make_context()
    executor = CommandExecutor()
    completed_before = _metric_value(COMMANDS_COMPLETED_TOTAL, command_type=context.command_type)

    result = await executor.execute(handler, context, {"a": 1})

    assert result.status is CommandResultStatus.SUCCESS
    assert result.result == {"echoed": {"a": 1}}
    assert result.exit_code == EXIT_CODE_SUCCESS
    assert result.duration_seconds >= 0
    assert (
        _metric_value(COMMANDS_COMPLETED_TOTAL, command_type=context.command_type)
        == completed_before + 1
    )
    assert executor.running_count == 0


@pytest.mark.asyncio
async def test_failing_execution_returns_failed_result_without_stack_trace_by_default() -> None:
    """An exception in execute() produces a FAILED result; no stack trace unless debug."""

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        raise RuntimeError("boom")

    handler = _ScriptedHandler(behavior=behavior)
    context = _make_context(debug=False)
    executor = CommandExecutor()
    failed_before = _metric_value(COMMANDS_FAILED_TOTAL, command_type=context.command_type)

    result = await executor.execute(handler, context, {})

    assert result.status is CommandResultStatus.FAILED
    assert result.error_message == "boom"
    assert result.stack_trace is None
    assert result.exit_code == EXIT_CODE_FAILURE
    assert (
        _metric_value(COMMANDS_FAILED_TOTAL, command_type=context.command_type) == failed_before + 1
    )


@pytest.mark.asyncio
async def test_failing_execution_includes_stack_trace_in_debug_mode() -> None:
    """With settings.debug=True, a FAILED result carries a stack trace."""

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        raise RuntimeError("boom")

    handler = _ScriptedHandler(behavior=behavior)
    context = _make_context(debug=True)
    executor = CommandExecutor()

    result = await executor.execute(handler, context, {})

    assert result.stack_trace is not None
    assert "RuntimeError" in result.stack_trace


@pytest.mark.asyncio
async def test_timeout_produces_timeout_result_and_cancels_the_handler_task() -> None:
    """A handler that outlives its timeout is cancelled and reported as TIMEOUT."""
    cancelled = asyncio.Event()

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    handler = _ScriptedHandler(behavior=behavior, timeout_seconds=0.02)
    context = _make_context()
    executor = CommandExecutor()
    timeout_before = _metric_value(COMMANDS_TIMEOUT_TOTAL, command_type=context.command_type)

    result = await executor.execute(handler, context, {})

    assert result.status is CommandResultStatus.TIMEOUT
    assert result.exit_code == EXIT_CODE_TIMEOUT
    assert "timed out" in (result.error_message or "")
    assert (
        _metric_value(COMMANDS_TIMEOUT_TOTAL, command_type=context.command_type)
        == timeout_before + 1
    )
    assert cancelled.is_set()
    assert executor.running_count == 0


@pytest.mark.asyncio
async def test_cancel_returns_false_for_an_unknown_command_id() -> None:
    """cancel() for a command_id that isn't running returns False."""
    executor = CommandExecutor()
    assert await executor.cancel(uuid4()) is False


@pytest.mark.asyncio
async def test_cancel_stops_a_running_command_and_reports_cancelled() -> None:
    """Calling cancel() on a running command produces a CANCELLED result."""
    started = asyncio.Event()

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        started.set()
        await asyncio.sleep(10)

    command_id = uuid4()
    handler = _ScriptedHandler(behavior=behavior, timeout_seconds=5.0)
    context = _make_context(command_id=command_id)
    executor = CommandExecutor()

    execute_task = asyncio.create_task(executor.execute(handler, context, {}))
    await started.wait()
    assert executor.running_count == 1
    cancelled = await executor.cancel(command_id)
    result = await execute_task

    assert cancelled is True
    assert result.status is CommandResultStatus.CANCELLED
    assert result.exit_code == EXIT_CODE_CANCELLED
    assert executor.running_count == 0


@pytest.mark.asyncio
async def test_retries_disabled_by_default_means_one_attempt() -> None:
    """With the default ExecutorConfig, a failure is never retried."""

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        raise RuntimeError("always fails")

    handler = _ScriptedHandler(behavior=behavior)
    executor = CommandExecutor()

    result = await executor.execute(handler, _make_context(), {})

    assert result.status is CommandResultStatus.FAILED
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_retries_retry_only_on_failure_up_to_max_retries() -> None:
    """max_retries=2 allows up to two retries after an initial failure."""

    async def behavior(
        call: int, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if call < 3:
            raise RuntimeError(f"attempt {call} failed")
        return {"ok": True}

    handler = _ScriptedHandler(behavior=behavior)
    executor = CommandExecutor(config=ExecutorConfig(max_retries=2))

    result = await executor.execute(handler, _make_context(), {})

    assert result.status is CommandResultStatus.SUCCESS
    assert handler.calls == 3


@pytest.mark.asyncio
async def test_retries_stop_at_max_retries_if_still_failing() -> None:
    """Exhausting max_retries still returns the last FAILED result."""

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        raise RuntimeError(f"attempt {call} failed")

    handler = _ScriptedHandler(behavior=behavior)
    executor = CommandExecutor(config=ExecutorConfig(max_retries=2))

    result = await executor.execute(handler, _make_context(), {})

    assert result.status is CommandResultStatus.FAILED
    assert handler.calls == 3
    assert "attempt 3 failed" in (result.error_message or "")


@pytest.mark.asyncio
async def test_timeout_and_cancelled_results_are_never_retried() -> None:
    """A TIMEOUT never triggers a retry, even with retries enabled."""

    async def behavior(call: int, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        await asyncio.sleep(10)

    handler = _ScriptedHandler(behavior=behavior, timeout_seconds=0.01)
    executor = CommandExecutor(config=ExecutorConfig(max_retries=3))

    result = await executor.execute(handler, _make_context(), {})

    assert result.status is CommandResultStatus.TIMEOUT
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_execution_duration_is_recorded() -> None:
    """The duration histogram receives an observation on every terminal outcome."""

    async def behavior(
        call: int, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return {}

    handler = _ScriptedHandler(behavior=behavior, command_type="test.duration")
    executor = CommandExecutor()

    await executor.execute(handler, _make_context(command_type="test.duration"), {})

    family = next(iter(COMMAND_EXECUTION_DURATION_SECONDS.collect()))
    assert any(
        sample.labels.get("command_type") == "test.duration" and sample.name.endswith("_count")
        for sample in family.samples
    )
