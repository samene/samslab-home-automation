"""One physical WebSocket connection: outgoing queue, backpressure, and delivery tracking."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

import structlog
from fastapi import WebSocket

from app.websocket.constants import ACK_WATCHDOG_INTERVAL_SECONDS, MAX_SEEN_MESSAGE_IDS
from app.websocket.exceptions import BackpressureExceededError
from app.websocket.metrics import BYTES_SENT_TOTAL, MESSAGES_SENT_TOTAL
from app.websocket.protocol import ACK_REQUIRED_MESSAGE_TYPES
from app.websocket.schemas import Envelope
from app.websocket.serializer import serialize

logger: Any = structlog.get_logger("websocket.connection")


@dataclass
class PendingAck:
    """Bookkeeping for one outgoing message awaiting a ``MESSAGE_ACK``."""

    envelope: Envelope
    attempts: int
    deadline: float


class Connection:
    """Own the bounded outgoing queue and delivery/duplicate-detection state for one socket.

    Backpressure is enforced by never blocking on a full queue: ``enqueue``
    raises immediately so the caller can disconnect a slow client instead of
    growing memory without bound.
    """

    def __init__(
        self,
        websocket: WebSocket,
        *,
        queue_size: int,
        ack_timeout_seconds: float,
        ack_max_retries: int,
    ) -> None:
        """Bind to one accepted WebSocket for the lifetime of its connection."""
        self._websocket = websocket
        self._queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=queue_size)
        self.pending_acks: dict[UUID, PendingAck] = {}
        self._seen_incoming_ids: OrderedDict[UUID, None] = OrderedDict()
        self._ack_timeout_seconds = ack_timeout_seconds
        self._ack_max_retries = ack_max_retries

    def enqueue(self, envelope: Envelope) -> None:
        """Queue an outgoing message, tracking it for acknowledgement if required."""
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull as error:
            raise BackpressureExceededError("Outgoing queue is full") from error
        if envelope.message_type in ACK_REQUIRED_MESSAGE_TYPES:
            self.pending_acks[envelope.message_id] = PendingAck(
                envelope=envelope, attempts=0, deadline=monotonic() + self._ack_timeout_seconds
            )

    def record_ack(self, message_id: UUID) -> None:
        """Resolve one pending outgoing message once its ``MESSAGE_ACK`` arrives."""
        self.pending_acks.pop(message_id, None)

    def is_duplicate(self, message_id: UUID) -> bool:
        """Return whether an incoming message ID was already processed on this connection."""
        return message_id in self._seen_incoming_ids

    def mark_seen(self, message_id: UUID) -> None:
        """Remember an incoming message ID within a bounded window for duplicate detection."""
        self._seen_incoming_ids[message_id] = None
        if len(self._seen_incoming_ids) > MAX_SEEN_MESSAGE_IDS:
            self._seen_incoming_ids.popitem(last=False)

    async def writer_loop(self) -> None:
        """Drain the outgoing queue to the socket until cancelled."""
        while True:
            envelope = await self._queue.get()
            data = serialize(envelope)
            await self._websocket.send_text(data)
            MESSAGES_SENT_TOTAL.labels(message_type=envelope.message_type.value).inc()
            BYTES_SENT_TOTAL.inc(len(data))

    async def ack_watchdog_loop(self) -> None:
        """Retry or time out outgoing messages that went unacknowledged."""
        while True:
            await asyncio.sleep(ACK_WATCHDOG_INTERVAL_SECONDS)
            now = monotonic()
            for message_id, pending in list(self.pending_acks.items()):
                if now < pending.deadline:
                    continue
                if pending.attempts >= self._ack_max_retries:
                    del self.pending_acks[message_id]
                    logger.warning(
                        "message_ack_timeout",
                        message_id=str(message_id),
                        message_type=pending.envelope.message_type.value,
                    )
                    continue
                pending.attempts += 1
                pending.deadline = now + self._ack_timeout_seconds
                try:
                    self._queue.put_nowait(pending.envelope)
                except asyncio.QueueFull:
                    logger.warning(
                        "message_ack_retry_dropped",
                        message_id=str(message_id),
                        message_type=pending.envelope.message_type.value,
                    )

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        """Close the underlying socket, tolerating an already-closed connection."""
        try:
            await self._websocket.close(code=code, reason=reason)
        except Exception:
            logger.debug("websocket_close_ignored")
