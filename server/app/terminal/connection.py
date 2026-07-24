"""One browser's WebSocket connection to the terminal transport.

A deliberately smaller sibling of ``app/websocket/connection.py``'s
``Connection``: this leg never tracks per-message acknowledgement or
duplicate incoming IDs (see ``shared.protocol.message_types.TERMINAL_MESSAGE_TYPES``
— terminal traffic is excluded from that machinery on both legs, for the same
reason), it only needs the bounded outgoing queue + backpressure half.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import WebSocket

from app.terminal.exceptions import TerminalGatewayError
from app.websocket.schemas import Envelope
from app.websocket.serializer import serialize

logger: Any = structlog.get_logger("terminal.connection")


class BackpressureExceededError(TerminalGatewayError):
    """Raised when a browser connection's bounded outgoing queue is full."""


class BrowserConnection:
    """Owns the bounded outgoing queue for one browser's terminal WebSocket."""

    def __init__(self, websocket: WebSocket, *, queue_size: int) -> None:
        self._websocket = websocket
        self._queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=queue_size)

    def enqueue(self, envelope: Envelope) -> None:
        """Queue an outgoing message; raises immediately rather than blocking on a full queue."""
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull as error:
            raise BackpressureExceededError("Outgoing queue is full") from error

    async def writer_loop(self) -> None:
        """Drain the outgoing queue to the socket until cancelled."""
        while True:
            envelope = await self._queue.get()
            await self._websocket.send_text(serialize(envelope))

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        """Close the underlying socket, tolerating an already-closed connection."""
        try:
            await self._websocket.close(code=code, reason=reason)
        except Exception:
            logger.debug("terminal_websocket_close_ignored")
