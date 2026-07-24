"""Generic, business-logic-free handling for each post-handshake message type.

No handler here calls ``CommandApplicationService`` or any other cross-domain
service directly. ``COMMAND_ACK``/``COMMAND_RESULT`` are the one exception to
"generic only": their payload is parsed enough to publish a transient
``CommandAckReceived``/``CommandResultReceived`` event on the shared event
bus — the same one-way notification seam ``DeviceHeartbeat`` already uses —
so the Command Dispatcher can react without this module ever importing it or
knowing it exists. Every message type still gets its generic ``MESSAGE_ACK``
reply regardless, matching the gateway's transport-only responsibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ValidationError

from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    CommandAckReceived,
    CommandResultReceived,
    TerminalClosedReceived,
    TerminalErrorReceived,
    TerminalOpenedReceived,
    TerminalOutputReceived,
)
from app.websocket.connection import Connection
from app.websocket.exceptions import ProtocolViolationError
from app.websocket.metrics import MESSAGES_RECEIVED_TOTAL
from app.websocket.protocol import MessageType
from app.websocket.schemas import (
    CommandAckPayload,
    CommandResultPayload,
    Envelope,
    ErrorPayload,
    MessageAckPayload,
    PongPayload,
    TerminalClosedPayload,
    TerminalErrorPayload,
    TerminalOpenedPayload,
    TerminalOutputPayload,
)
from app.websocket.session import Session

#: Message types that receive a generic ``MESSAGE_ACK`` reply once logged.
_ACKNOWLEDGED_MESSAGE_TYPES = frozenset(
    {
        MessageType.COMMAND,
        MessageType.EVENT,
        MessageType.LOG,
    }
)


def _validate_payload(
    model: type[BaseModel], payload: dict[str, Any], message_type: MessageType
) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise ProtocolViolationError(f"Invalid {message_type.value} payload: {error}") from error


async def dispatch_message(
    *,
    session: Session,
    connection: Connection,
    envelope: Envelope,
    log: Any = None,
    event_bus: EventBus | None = None,
) -> None:
    """Handle one already-deserialized, non-duplicate, post-handshake message."""
    logger = log or structlog.get_logger("websocket.handlers")
    session.last_seen = datetime.now(UTC)
    MESSAGES_RECEIVED_TOTAL.labels(message_type=envelope.message_type.value).inc()
    logger = logger.bind(
        message_id=str(envelope.message_id), message_type=envelope.message_type.value
    )

    if envelope.message_type is MessageType.PING:
        connection.enqueue(
            Envelope(
                protocol_version=session.protocol_version,
                message_type=MessageType.PONG,
                payload=PongPayload(sent_at=datetime.now(UTC)).model_dump(mode="json"),
                correlation_id=envelope.message_id,
            )
        )
        return

    if envelope.message_type is MessageType.PONG:
        return

    if envelope.message_type is MessageType.MESSAGE_ACK:
        ack: MessageAckPayload = _validate_payload(
            MessageAckPayload, envelope.payload, envelope.message_type
        )
        connection.record_ack(ack.acknowledged_message_id)
        return

    if envelope.message_type is MessageType.ERROR:
        error: ErrorPayload = _validate_payload(
            ErrorPayload, envelope.payload, envelope.message_type
        )
        logger.warning("websocket_client_error", code=error.code, message=error.message)
        return

    if envelope.message_type is MessageType.COMMAND_ACK:
        ack_payload: CommandAckPayload = _validate_payload(
            CommandAckPayload, envelope.payload, envelope.message_type
        )
        logger.info("websocket_command_ack_received", command_id=str(ack_payload.command_id))
        # COMMAND_ACK is the business-specific reply to the original outgoing
        # COMMAND envelope (correlation_id carries that envelope's message_id
        # — see the agent's _send_ack) — it must resolve that envelope's own
        # transport-level pending-ack too, or Connection.ack_watchdog_loop
        # never learns delivery succeeded and keeps resending the COMMAND
        # every WS_MESSAGE_ACK_TIMEOUT_SECONDS until it exhausts its retries,
        # regardless of the command already having been handled correctly.
        if envelope.correlation_id is not None:
            connection.record_ack(envelope.correlation_id)
        if event_bus is not None:
            await event_bus.publish(
                CommandAckReceived(
                    command_id=ack_payload.command_id,
                    device_id=session.device_id,
                    message_id=envelope.message_id,
                    occurred_at=datetime.now(UTC),
                )
            )
        _send_message_ack(connection, session, envelope.message_id)
        return

    if envelope.message_type is MessageType.COMMAND_RESULT:
        result_payload: CommandResultPayload = _validate_payload(
            CommandResultPayload, envelope.payload, envelope.message_type
        )
        logger.info(
            "websocket_command_result_received",
            command_id=str(result_payload.command_id),
            success=result_payload.success,
        )
        # Same reasoning as COMMAND_ACK above: also resolves the original
        # COMMAND's pending-ack in the (should-be-rare) case its COMMAND_ACK
        # was somehow missed but the result still arrived.
        if envelope.correlation_id is not None:
            connection.record_ack(envelope.correlation_id)
        if event_bus is not None:
            await event_bus.publish(
                CommandResultReceived(
                    command_id=result_payload.command_id,
                    device_id=session.device_id,
                    success=result_payload.success,
                    result=result_payload.result or {},
                    error_message=result_payload.error_message,
                    occurred_at=datetime.now(UTC),
                )
            )
        _send_message_ack(connection, session, envelope.message_id)
        return

    if envelope.message_type is MessageType.TERMINAL_OPENED:
        opened_payload: TerminalOpenedPayload = _validate_payload(
            TerminalOpenedPayload, envelope.payload, envelope.message_type
        )
        logger.info("websocket_terminal_opened_received", session_id=str(opened_payload.session_id))
        if event_bus is not None:
            await event_bus.publish(
                TerminalOpenedReceived(
                    device_id=session.device_id,
                    session_id=opened_payload.session_id,
                    shell=opened_payload.shell,
                    occurred_at=datetime.now(UTC),
                )
            )
        _send_message_ack(connection, session, envelope.message_id)
        return

    if envelope.message_type is MessageType.TERMINAL_OUTPUT:
        # Deliberately no MESSAGE_ACK here — see
        # shared.protocol.message_types.TERMINAL_MESSAGE_TYPES: a
        # high-frequency byte stream is not worth transport-level ack/retry.
        output_payload: TerminalOutputPayload = _validate_payload(
            TerminalOutputPayload, envelope.payload, envelope.message_type
        )
        if event_bus is not None:
            await event_bus.publish(
                TerminalOutputReceived(
                    device_id=session.device_id,
                    session_id=output_payload.session_id,
                    data=output_payload.data,
                    occurred_at=datetime.now(UTC),
                )
            )
        return

    if envelope.message_type is MessageType.TERMINAL_CLOSED:
        closed_payload: TerminalClosedPayload = _validate_payload(
            TerminalClosedPayload, envelope.payload, envelope.message_type
        )
        logger.info(
            "websocket_terminal_closed_received",
            session_id=str(closed_payload.session_id),
            reason=closed_payload.reason,
        )
        if event_bus is not None:
            await event_bus.publish(
                TerminalClosedReceived(
                    device_id=session.device_id,
                    session_id=closed_payload.session_id,
                    reason=closed_payload.reason,
                    exit_code=closed_payload.exit_code,
                    occurred_at=datetime.now(UTC),
                )
            )
        _send_message_ack(connection, session, envelope.message_id)
        return

    if envelope.message_type is MessageType.TERMINAL_ERROR:
        error_payload: TerminalErrorPayload = _validate_payload(
            TerminalErrorPayload, envelope.payload, envelope.message_type
        )
        logger.warning(
            "websocket_terminal_error_received",
            session_id=str(error_payload.session_id) if error_payload.session_id else None,
            code=error_payload.code,
        )
        if event_bus is not None:
            await event_bus.publish(
                TerminalErrorReceived(
                    device_id=session.device_id,
                    session_id=error_payload.session_id,
                    code=error_payload.code,
                    message=error_payload.message,
                    occurred_at=datetime.now(UTC),
                )
            )
        _send_message_ack(connection, session, envelope.message_id)
        return

    if envelope.message_type in _ACKNOWLEDGED_MESSAGE_TYPES:
        logger.info("websocket_message_received")
        _send_message_ack(connection, session, envelope.message_id)
        return

    logger.warning("websocket_unexpected_message_type")


def _send_message_ack(
    connection: Connection, session: Session, acknowledged_message_id: UUID
) -> None:
    connection.enqueue(
        Envelope(
            protocol_version=session.protocol_version,
            message_type=MessageType.MESSAGE_ACK,
            payload=MessageAckPayload(acknowledged_message_id=acknowledged_message_id).model_dump(
                mode="json"
            ),
            correlation_id=acknowledged_message_id,
        )
    )
