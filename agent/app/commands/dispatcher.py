"""Wires COMMAND envelopes to the command runtime: validate, ack, execute, result.

``CommandDispatcher.handle_command`` is registered on the transport-level
``MessageDispatcher`` (``app/dispatcher/dispatcher.py``) for ``MessageType.COMMAND``
— it's the one seam between the two. Everything below that seam (registry,
context, executor, lifecycle) never imports anything transport-specific, and
``handle_command`` never lets an exception escape back into the transport:
a single malformed or misbehaving command must never take down the
WebSocket connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog
from pydantic import ValidationError

from app.commands.context import CommandServices, build_command_context
from app.commands.events import CommandEventBus
from app.commands.exceptions import CommandValidationError, HandlerNotFoundError
from app.commands.executor import CommandExecutor
from app.commands.lifecycle import (
    RESULT_STATUS_TO_LIFECYCLE_STATE,
    CommandLifecycle,
    CommandLifecycleState,
)
from app.commands.metrics import COMMANDS_RECEIVED_TOTAL
from app.commands.registry import CommandRegistry
from app.commands.result import EXIT_CODE_FAILURE, CommandResult, CommandResultStatus
from app.config.settings import AgentSettings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import (
    CommandAckPayload,
    CommandPayload,
    CommandResultPayload,
    Envelope,
)

logger = structlog.get_logger(__name__)

Sender = Callable[[Envelope], Awaitable[None]]


class CommandDispatcher:
    """Receives COMMAND, sends COMMAND_ACK, executes, sends COMMAND_RESULT."""

    def __init__(
        self,
        *,
        registry: CommandRegistry,
        executor: CommandExecutor,
        event_bus: CommandEventBus,
        settings: AgentSettings,
        services: CommandServices,
        send: Sender,
        agent_version: str,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._event_bus = event_bus
        self._settings = settings
        self._services = services
        self._send = send
        self._agent_version = agent_version
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle_command(self, envelope: Envelope) -> None:
        """The ``MessageDispatcher``-registered handler for ``MessageType.COMMAND``.

        Parses just enough to hand processing off as its own task and returns
        immediately — the receive loop must never block on command
        execution, and one command must never block another.
        """
        try:
            payload = CommandPayload.model_validate(envelope.payload)
        except ValidationError as error:
            logger.warning("command.malformed_envelope", error=str(error))
            return
        COMMANDS_RECEIVED_TOTAL.labels(command_type=payload.command_type).inc()
        task = asyncio.create_task(self._process(envelope, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _process(self, envelope: Envelope, payload: CommandPayload) -> None:
        bound_logger = logger.bind(
            command_id=str(payload.command_id),
            command_type=payload.command_type,
            correlation_id=str(envelope.correlation_id) if envelope.correlation_id else None,
            trace_id=envelope.trace_id,
        )
        lifecycle = CommandLifecycle(
            command_id=payload.command_id,
            command_type=payload.command_type,
            event_bus=self._event_bus,
        )
        try:
            await self._process_unsafe(envelope, payload, lifecycle, bound_logger)
        except Exception as error:  # last-resort safety net; the transport must never see this
            bound_logger.exception("command.unexpected_error", error=str(error))
            with suppress(Exception):
                await self._send_result(
                    envelope,
                    CommandResult(
                        command_id=payload.command_id,
                        status=CommandResultStatus.FAILED,
                        duration_seconds=0.0,
                        error_message=f"Unexpected error: {error}",
                        exit_code=EXIT_CODE_FAILURE,
                    ),
                )

    async def _process_unsafe(
        self,
        envelope: Envelope,
        payload: CommandPayload,
        lifecycle: CommandLifecycle,
        bound_logger: structlog.typing.FilteringBoundLogger,
    ) -> None:
        try:
            handler = self._registry.find_handler(payload.command_type)
        except HandlerNotFoundError as error:
            bound_logger.warning("command.handler_not_found", error=str(error))
            lifecycle.transition_to(CommandLifecycleState.FAILED, detail={"error": str(error)})
            await self._send_result(
                envelope,
                CommandResult(
                    command_id=payload.command_id,
                    status=CommandResultStatus.FAILED,
                    duration_seconds=0.0,
                    error_message=str(error),
                    exit_code=EXIT_CODE_FAILURE,
                ),
            )
            return

        context = build_command_context(
            envelope=envelope,
            payload=payload,
            settings=self._settings,
            services=self._services,
            agent_version=self._agent_version,
            logger=bound_logger,
        )

        try:
            await handler.validate(context, payload.arguments)
        except CommandValidationError as error:
            bound_logger.warning("command.validation_failed", error=str(error))
            lifecycle.transition_to(CommandLifecycleState.FAILED, detail={"error": str(error)})
            await self._send_result(
                envelope,
                CommandResult(
                    command_id=payload.command_id,
                    status=CommandResultStatus.FAILED,
                    duration_seconds=0.0,
                    error_message=str(error),
                    exit_code=EXIT_CODE_FAILURE,
                ),
            )
            return
        lifecycle.transition_to(CommandLifecycleState.VALIDATED)

        await self._send_ack(envelope, payload)
        lifecycle.transition_to(CommandLifecycleState.ACKNOWLEDGED)
        lifecycle.transition_to(CommandLifecycleState.RUNNING)

        result = await self._executor.execute(handler, context, payload.arguments)
        lifecycle.transition_to(
            RESULT_STATUS_TO_LIFECYCLE_STATE[result.status], detail={"exit_code": result.exit_code}
        )

        bound_logger.info(
            "command.finished",
            handler=handler.command_type,
            status=result.status.value,
            duration=result.duration_seconds,
        )
        await self._send_result(envelope, result)

    async def _send_ack(self, envelope: Envelope, payload: CommandPayload) -> None:
        ack = Envelope(
            protocol_version=envelope.protocol_version,
            message_type=MessageType.COMMAND_ACK,
            payload=CommandAckPayload(command_id=payload.command_id).model_dump(mode="json"),
            correlation_id=envelope.message_id,
        )
        await self._send(ack)

    async def _send_result(self, envelope: Envelope, result: CommandResult) -> None:
        error_message = result.error_message
        if result.status is not CommandResultStatus.SUCCESS and error_message is not None:
            error_message = f"{result.status.value}: {error_message}"
        result_payload = CommandResultPayload(
            command_id=result.command_id,
            success=result.status is CommandResultStatus.SUCCESS,
            result=dict(result.result) if result.result is not None else None,
            error_message=error_message,
        )
        envelope_out = Envelope(
            protocol_version=envelope.protocol_version,
            message_type=MessageType.COMMAND_RESULT,
            payload=result_payload.model_dump(mode="json"),
            correlation_id=envelope.message_id,
        )
        await self._send(envelope_out)

    async def aclose(self) -> None:
        """Cancel every still-in-flight command-processing task; best-effort, for shutdown."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
