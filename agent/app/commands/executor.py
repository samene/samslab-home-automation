"""Runs one handler's ``execute()`` as its own task: timeout, cancellation, retries, metrics.

Each command executes as an independent ``asyncio.Task`` — one slow or failed
command never blocks another, and never blocks the WebSocket connection's own
receive/heartbeat loops (which never await this module directly; the
dispatcher hands execution off as its own task too — see ``dispatcher.py``).
"""

from __future__ import annotations

import asyncio
import time
import traceback
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.commands.context import CommandContext
from app.commands.handler import CommandHandler
from app.commands.metrics import (
    COMMAND_EXECUTION_DURATION_SECONDS,
    COMMANDS_COMPLETED_TOTAL,
    COMMANDS_FAILED_TOTAL,
    COMMANDS_TIMEOUT_TOTAL,
    RUNNING_COMMANDS,
)
from app.commands.result import (
    EXIT_CODE_CANCELLED,
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_TIMEOUT,
    CommandResult,
    CommandResultStatus,
)


@dataclass(frozen=True)
class ExecutorConfig:
    """Executor-wide policy. Retries are disabled by default."""

    max_retries: int = 0


class CommandExecutor:
    """Executes commands independently, each in its own tracked ``asyncio.Task``."""

    def __init__(self, *, config: ExecutorConfig | None = None) -> None:
        self._config = config or ExecutorConfig()
        self._running: dict[UUID, asyncio.Task[Mapping[str, Any] | None]] = {}

    @property
    def running_count(self) -> int:
        """Number of commands currently executing."""
        return len(self._running)

    async def execute(
        self, handler: CommandHandler, context: CommandContext, arguments: Mapping[str, Any]
    ) -> CommandResult:
        """Run ``handler.execute()`` to a terminal ``CommandResult``, retrying only on FAILED.

        With the default ``max_retries=0`` this makes exactly one attempt.
        TIMEOUT and CANCELLED are never retried — a timed-out operation may
        still be running server-side-visible side effects, and a cancellation
        is explicit intent, not a transient failure.
        """
        attempt = 0
        while True:
            attempt += 1
            result = await self._execute_once(handler, context, arguments)
            if result.status is CommandResultStatus.FAILED and attempt <= self._config.max_retries:
                continue
            return result

    async def _execute_once(
        self, handler: CommandHandler, context: CommandContext, arguments: Mapping[str, Any]
    ) -> CommandResult:
        timeout = handler.timeout()
        started = time.monotonic()
        task: asyncio.Task[Mapping[str, Any] | None] = asyncio.ensure_future(
            handler.execute(context, arguments)
        )
        # A duplicate command_id arriving while the first is still running would
        # overwrite this entry; the earlier task keeps running to completion
        # independently, it just becomes untrackable via cancel(). Not handled
        # further — an accepted, documented limitation for this phase.
        self._running[context.command_id] = task
        RUNNING_COMMANDS.set(len(self._running))
        try:
            return await self._await_result(task, handler, context, timeout, started)
        finally:
            self._running.pop(context.command_id, None)
            RUNNING_COMMANDS.set(len(self._running))

    async def _await_result(
        self,
        task: asyncio.Task[Mapping[str, Any] | None],
        handler: CommandHandler,
        context: CommandContext,
        timeout: float,
        started: float,
    ) -> CommandResult:
        command_type = context.command_type
        try:
            data = await asyncio.wait_for(task, timeout=timeout)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            duration = time.monotonic() - started
            COMMANDS_TIMEOUT_TOTAL.labels(command_type=command_type).inc()
            COMMAND_EXECUTION_DURATION_SECONDS.labels(command_type=command_type).observe(duration)
            return CommandResult(
                command_id=context.command_id,
                status=CommandResultStatus.TIMEOUT,
                duration_seconds=duration,
                error_message=f"Command timed out after {timeout}s",
                exit_code=EXIT_CODE_TIMEOUT,
            )
        except asyncio.CancelledError:
            # Deliberately not re-raised: this executor's contract is "always
            # produce a CommandResult", including when cancel() (or an outer
            # shutdown) cancels the in-flight task — the dispatcher still
            # reports CANCELLED back to the server rather than losing the
            # command silently.
            duration = time.monotonic() - started
            return CommandResult(
                command_id=context.command_id,
                status=CommandResultStatus.CANCELLED,
                duration_seconds=duration,
                error_message="Command was cancelled",
                exit_code=EXIT_CODE_CANCELLED,
            )
        except Exception as error:
            duration = time.monotonic() - started
            COMMANDS_FAILED_TOTAL.labels(command_type=command_type).inc()
            COMMAND_EXECUTION_DURATION_SECONDS.labels(command_type=command_type).observe(duration)
            stack_trace = traceback.format_exc() if context.settings.debug else None
            return CommandResult(
                command_id=context.command_id,
                status=CommandResultStatus.FAILED,
                duration_seconds=duration,
                error_message=str(error),
                stack_trace=stack_trace,
                exit_code=EXIT_CODE_FAILURE,
            )
        else:
            duration = time.monotonic() - started
            COMMANDS_COMPLETED_TOTAL.labels(command_type=command_type).inc()
            COMMAND_EXECUTION_DURATION_SECONDS.labels(command_type=command_type).observe(duration)
            return CommandResult(
                command_id=context.command_id,
                status=CommandResultStatus.SUCCESS,
                duration_seconds=duration,
                result=data,
                exit_code=EXIT_CODE_SUCCESS,
            )

    async def cancel(self, command_id: UUID) -> bool:
        """Cancel a running command's task; returns ``False`` if it isn't tracked."""
        task = self._running.get(command_id)
        if task is None:
            return False
        task.cancel()
        return True
