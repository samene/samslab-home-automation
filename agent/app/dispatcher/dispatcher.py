"""A message-type keyed routing table for incoming protocol envelopes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope

logger = structlog.get_logger(__name__)

MessageHandler = Callable[[Envelope], Awaitable[None]]


class MessageDispatcher:
    """Routes one received envelope to the handler registered for its message type.

    An unregistered message type (e.g. COMMAND, intentionally unhandled this
    phase) is logged and ignored rather than raising — this is a routing
    layer, not a place for business logic or a single unknown message to halt
    the connection.
    """

    def __init__(self) -> None:
        self._handlers: dict[MessageType, MessageHandler] = {}

    def register(self, message_type: MessageType, handler: MessageHandler) -> None:
        """Register (or replace) the handler invoked for ``message_type``."""
        self._handlers[message_type] = handler

    async def dispatch(self, envelope: Envelope) -> None:
        """Invoke the handler registered for ``envelope.message_type``, if any."""
        handler = self._handlers.get(envelope.message_type)
        if handler is None:
            logger.debug("dispatcher.unhandled_message_type", message_type=envelope.message_type)
            return
        await handler(envelope)
