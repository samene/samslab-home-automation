"""PING/PONG liveness and idle-timeout enforcement for one connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog

from app.websocket.connection import Connection
from app.websocket.metrics import HEARTBEAT_FAILURES_TOTAL
from app.websocket.protocol import MessageType
from app.websocket.schemas import Envelope, PingPayload
from app.websocket.session import Session

logger: Any = structlog.get_logger("websocket.heartbeat")

TimeoutCallback = Callable[[Session, str], Awaitable[None]]


def build_ping_envelope(protocol_version: int) -> Envelope:
    """Build one outgoing ``PING`` envelope."""
    return Envelope(
        protocol_version=protocol_version,
        message_type=MessageType.PING,
        payload=PingPayload().model_dump(mode="json"),
    )


class HeartbeatMonitor:
    """Send periodic PINGs and detect both heartbeat and idle timeouts.

    A heartbeat timeout fires when a PING gets no reply (no message of any
    kind updates ``session.last_seen``) within ``heartbeat_timeout_seconds``.
    An idle timeout fires independently, whenever nothing at all has been
    heard from the agent for ``idle_timeout_seconds`` — a broader liveness
    check than the heartbeat cycle alone.
    """

    def __init__(
        self,
        session: Session,
        connection: Connection,
        *,
        interval_seconds: float,
        heartbeat_timeout_seconds: float,
        idle_timeout_seconds: float,
        on_timeout: TimeoutCallback,
    ) -> None:
        """Bind to one session/connection pair for the life of the connection."""
        self._session = session
        self._connection = connection
        self._interval_seconds = interval_seconds
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._idle_timeout_seconds = idle_timeout_seconds
        self._on_timeout = on_timeout

    async def run(self) -> None:
        """Loop until cancelled, sending PINGs and reacting to unresponsive agents."""
        while True:
            await asyncio.sleep(self._interval_seconds)
            now = datetime.now(UTC)
            idle_for = (now - self._session.last_seen).total_seconds()
            if idle_for > self._idle_timeout_seconds:
                logger.warning(
                    "websocket_idle_timeout",
                    device_id=str(self._session.device_id),
                    connection_id=str(self._session.connection_id),
                    idle_for_seconds=round(idle_for, 3),
                )
                await self._on_timeout(self._session, "idle_timeout")
                return
            last_seen_before_ping = self._session.last_seen
            self._connection.enqueue(build_ping_envelope(self._session.protocol_version))
            await asyncio.sleep(self._heartbeat_timeout_seconds)
            if self._session.last_seen == last_seen_before_ping:
                HEARTBEAT_FAILURES_TOTAL.inc()
                logger.warning(
                    "websocket_heartbeat_timeout",
                    device_id=str(self._session.device_id),
                    connection_id=str(self._session.connection_id),
                )
                await self._on_timeout(self._session, "heartbeat_timeout")
                return
