"""The agent's one outbound WebSocket connection to the cloud server.

Owns the transport lifecycle only: opening it, the HELLO/WELCOME handshake,
send/receive framing, heartbeats, and reconnect-with-backoff. It never
inspects a COMMAND payload or executes anything — routing a received envelope
to a handler is ``app.dispatcher``'s job, and the retry/heartbeat *loops* that
call these methods repeatedly live in ``app.lifecycle``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog

from app.config.settings import AgentSettings
from app.connection.backoff import ExponentialBackoff
from app.connection.exceptions import AuthenticationRejectedError, NotConnectedError
from app.connection.token_provider import fetch_device_token
from app.connection.transport import WebSocketConnection, WebSocketConnector, connect_websocket
from app.metrics.registry import (
    AGENT_CONNECTED,
    CONNECTION_ATTEMPTS_TOTAL,
    HEARTBEAT_FAILURES_TOTAL,
    HEARTBEAT_TOTAL,
    MESSAGES_RECEIVED_TOTAL,
    MESSAGES_SENT_TOTAL,
    RECONNECT_TOTAL,
)
from app.protocol.handlers import build_goodbye, build_hello, build_ping, parse_welcome
from app.services.session import SessionState
from app.state.machine import AgentState, StateMachine
from app.utils.version import AGENT_VERSION
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope
from shared.protocol.serializer import deserialize, serialize

logger = structlog.get_logger(__name__)

#: Signs an assertion and exchanges it for a device access token — injectable
#: the same way ``connector`` is, so tests never need a real HTTP round trip.
DeviceTokenProvider = Callable[[AgentSettings], Awaitable[str]]


class ConnectionManager:
    """Manages one connection's full lifecycle: connect, authenticate, heartbeat, disconnect."""

    def __init__(
        self,
        *,
        settings: AgentSettings,
        state_machine: StateMachine,
        session: SessionState,
        connector: WebSocketConnector = connect_websocket,
        backoff: ExponentialBackoff | None = None,
        token_provider: DeviceTokenProvider = fetch_device_token,
    ) -> None:
        self._settings = settings
        self._state_machine = state_machine
        self._session = session
        self._connector = connector
        self._backoff = backoff or ExponentialBackoff(base_seconds=settings.reconnect_interval)
        self._token_provider = token_provider
        self._connection: WebSocketConnection | None = None

    @property
    def is_connected(self) -> bool:
        """Whether the underlying transport is currently open."""
        return self._connection is not None

    async def connect(self) -> None:
        """Open the transport and complete the HELLO/WELCOME handshake.

        Raises whatever the connector or ``authenticate`` raises; callers
        decide whether/how to retry (see ``reconnect``).
        """
        self._state_machine.transition_to(AgentState.CONNECTING)
        CONNECTION_ATTEMPTS_TOTAL.inc()
        logger.info("connection.connecting", server_url=self._settings.server_url)
        self._connection = await self._connector(self._settings.server_url)
        self._session.mark_connected()
        await self.authenticate()

    async def authenticate(self) -> None:
        """Fetch a fresh device access token, then send HELLO and validate WELCOME.

        A new token is requested on every call, not cached across
        connections — this is what lets a reconnect succeed no matter how
        long the agent was disconnected, since it's minted from a private
        key that never expires, rather than a static, eventually-stale token.
        """
        self._state_machine.transition_to(AgentState.AUTHENTICATING)
        access_token = await self._token_provider(self._settings)
        hello = build_hello(
            protocol_version=self._settings.protocol_version,
            token=access_token,
            agent_version=AGENT_VERSION,
        )
        await self.send(hello)
        response = await self.receive()
        if response.message_type is not MessageType.WELCOME:
            raise AuthenticationRejectedError(f"Expected WELCOME, got {response.message_type}")
        welcome = parse_welcome(response)
        self._session.mark_authenticated(
            connection_id=welcome.session_id,
            protocol_version=welcome.protocol_version,
            agent_version=AGENT_VERSION,
            connected_at=datetime.now(UTC),
        )
        self._backoff.reset()
        AGENT_CONNECTED.set(1)
        self._state_machine.transition_to(AgentState.ONLINE)
        logger.info("connection.authenticated", connection_id=str(welcome.session_id))

    async def send(self, envelope: Envelope) -> None:
        """Serialize and send one envelope over the open transport."""
        if self._connection is None:
            raise NotConnectedError("Cannot send: no active connection")
        await self._connection.send(serialize(envelope))
        MESSAGES_SENT_TOTAL.labels(message_type=envelope.message_type.value).inc()

    async def receive(self) -> Envelope:
        """Receive and deserialize the next envelope from the open transport."""
        if self._connection is None:
            raise NotConnectedError("Cannot receive: no active connection")
        raw = await self._connection.recv()
        envelope = deserialize(raw)
        MESSAGES_RECEIVED_TOTAL.labels(message_type=envelope.message_type.value).inc()
        return envelope

    async def heartbeat(self) -> None:
        """Send a PING and record it; the PONG reply is handled by the dispatcher."""
        ping = build_ping(protocol_version=self._settings.protocol_version)
        try:
            await self.send(ping)
        except Exception:
            HEARTBEAT_FAILURES_TOTAL.inc()
            raise
        self._session.record_heartbeat(datetime.now(UTC))
        HEARTBEAT_TOTAL.inc()

    async def disconnect(self, *, reason: str | None = None) -> None:
        """Send a best-effort GOODBYE, close the transport, and reset session state."""
        if self._connection is not None:
            goodbye = build_goodbye(protocol_version=self._settings.protocol_version, reason=reason)
            try:
                await self.send(goodbye)
            except Exception as error:
                logger.warning("connection.goodbye_send_failed", error=str(error))
            try:
                await self._connection.close()
            except Exception as error:
                logger.warning("connection.close_failed", error=str(error))
            self._connection = None
        AGENT_CONNECTED.set(0)
        self._session.mark_disconnected()

    async def reconnect(self) -> None:
        """Wait out the current backoff delay, then attempt ``connect`` once more."""
        RECONNECT_TOTAL.inc()
        delay = self._backoff.next_delay()
        logger.info("connection.reconnect_wait", delay_seconds=delay)
        await asyncio.sleep(delay)
        await self.connect()
