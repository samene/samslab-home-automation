"""A minimal, real-protocol WebSocket client standing in for a Raspberry Pi agent.

Built directly on ``shared/protocol`` and the ``websockets`` client library —
never on the real agent's own internal framework (``agent/app/``). This keeps
``FakeAgent`` a true black-box test double for the wire protocol (exactly what
"connect exactly like a Raspberry Pi" means) and sidesteps the fact that
``agent/`` is a separate installable package with its own ``app.*`` namespace
that must never be imported alongside the server's own ``app.*`` in the same
process (see ``docs/development/INTEGRATION_TESTING.md``).

Supports exactly the four ``system.*`` command types the real agent's Phase 2
built-in handlers implement (``system.echo``/``ping``/``capabilities``/``health``)
— nothing else, matching the real agent exactly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import websockets
from websockets.asyncio.client import ClientConnection

from shared.protocol.message_types import MessageType
from shared.protocol.schemas import (
    CommandAckPayload,
    CommandPayload,
    CommandResultPayload,
    Envelope,
    GoodbyePayload,
    HelloPayload,
    PingPayload,
    PongPayload,
    WelcomePayload,
)
from shared.protocol.serializer import deserialize, serialize

#: The only command types this fake supports — matches the real agent's Phase 2 built-ins.
SUPPORTED_COMMAND_TYPES: tuple[str, ...] = (
    "system.echo",
    "system.ping",
    "system.capabilities",
    "system.health",
)

FAKE_AGENT_VERSION = "0.0.0-fake"


class FakeAgentError(Exception):
    """Raised when the fake agent's handshake or protocol expectations aren't met."""

    def __init__(
        self, message: str, *, close_code: int | None = None, close_reason: str | None = None
    ) -> None:
        super().__init__(message)
        self.close_code = close_code
        self.close_reason = close_reason


class _UnknownCommand(Exception):
    """Internal signal for an unsupported command_type; never escapes FakeAgent."""


class FakeAgent:
    """Connects, authenticates, and heartbeats exactly like the real agent.

    Failure-injection knobs (all opt-in, default off) simulate the scenarios
    ``docs/development/INTEGRATION_TESTING.md`` documents:

    - ``reply_delay`` / ``handler_delay`` — high latency / a slow handler.
    - ``drop_next_ack`` / ``drop_next_result`` — a lost ACK or a lost result.
    - ``duplicate_next_result`` — a duplicated result frame.
    - ``respond_to_commands = False`` — the agent never acks or replies at all.
    - ``simulate_crash()`` — an abrupt disconnect with no GOODBYE.
    """

    def __init__(
        self,
        *,
        agent_version: str = FAKE_AGENT_VERSION,
        capabilities: Sequence[str] = SUPPORTED_COMMAND_TYPES,
    ) -> None:
        self.agent_version = agent_version
        self.capabilities = list(capabilities)
        self.connection: ClientConnection | None = None
        self.session_id: UUID | None = None
        self.welcome: WelcomePayload | None = None
        self.sent: list[Envelope] = []
        self.received: list[Envelope] = []
        self._receive_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        # Failure injection — see the class docstring. reply_delay defaults to
        # a small positive value rather than 0: a real device replying over
        # WiFi/LAN always has *some* latency, and the dispatcher's own
        # mark_dispatched() DB write briefly races an ack that arrives with
        # none at all (the exact race server/tests/test_dispatcher_integration.py
        # documents and works around for its own in-process fake agent).
        self.reply_delay: float = 0.03
        self.handler_delay: float = 0.0
        self.drop_next_ack: bool = False
        self.drop_next_result: bool = False
        self.duplicate_next_result: bool = False
        self.respond_to_commands: bool = True

    @property
    def is_connected(self) -> bool:
        """Whether the underlying socket is currently open."""
        return self.connection is not None

    async def connect_raw(self, server_url: str) -> None:
        """Open the socket without the HELLO/WELCOME handshake — for protocol-violation tests."""
        self.connection = await websockets.connect(server_url)

    async def connect(
        self,
        server_url: str,
        token: str,
        *,
        protocol_version: int = 1,
        resume_cursor: str | None = None,
    ) -> WelcomePayload:
        """Open the socket and complete the HELLO/WELCOME handshake, exactly like a real agent."""
        self.connection = await websockets.connect(server_url)
        hello = Envelope(
            protocol_version=protocol_version,
            message_type=MessageType.HELLO,
            payload=HelloPayload(
                token=token,
                agent_version=self.agent_version,
                capabilities=self.capabilities,
                resume_cursor=resume_cursor,
            ).model_dump(mode="json"),
        )
        await self._send(hello)
        try:
            response = await self._recv()
        except websockets.exceptions.ConnectionClosed as error:
            self.connection = None
            received_close = error.rcvd
            raise FakeAgentError(
                "Connection closed during handshake",
                close_code=received_close.code if received_close else None,
                close_reason=received_close.reason if received_close else None,
            ) from error
        if response.message_type is not MessageType.WELCOME:
            raise FakeAgentError(f"Expected WELCOME, got {response.message_type}")
        self.welcome = WelcomePayload.model_validate(response.payload)
        self.session_id = self.welcome.session_id
        self._receive_task = asyncio.create_task(self._receive_loop())
        return self.welcome

    async def disconnect(self, *, reason: str | None = None) -> None:
        """Send a graceful GOODBYE and close — a real agent's normal shutdown."""
        if self.connection is None:
            return
        with suppress(websockets.exceptions.ConnectionClosed, FakeAgentError):
            await self._send(
                Envelope(
                    protocol_version=1,
                    message_type=MessageType.GOODBYE,
                    payload=GoodbyePayload(reason=reason).model_dump(mode="json"),
                )
            )
        await self._teardown()

    async def simulate_crash(self) -> None:
        """Abruptly close the socket with no GOODBYE — a powered-off or crashed device."""
        if self.connection is None:
            return
        with suppress(Exception):
            await self.connection.close(code=1006, reason="simulated crash")
        await self._teardown()

    def start_heartbeat(self, interval: float = 1.0) -> None:
        """Start sending agent-initiated PING every ``interval`` seconds, like a real agent."""
        if self._heartbeat_task is not None:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval))

    async def send_heartbeat(self) -> None:
        """Send one agent-initiated PING immediately."""
        await self._send(
            Envelope(
                protocol_version=1,
                message_type=MessageType.PING,
                payload=PingPayload(sent_at=datetime.now(UTC)).model_dump(mode="json"),
            )
        )

    async def send_envelope(self, envelope: Envelope) -> None:
        """Send one already-built envelope — the escape hatch for duplicate/out-of-order tests."""
        await self._send(envelope)

    async def send_raw_text(self, text: str) -> None:
        """Send arbitrary raw text, bypassing envelope construction — for protocol-violation tests."""
        if self.connection is None:
            raise FakeAgentError("Not connected")
        await self.connection.send(text)

    async def recv_envelope(self, *, timeout: float = 5.0) -> Envelope:
        """Receive and record the next envelope directly.

        Only safe before ``connect()`` starts the background receive loop, or
        after it has stopped — otherwise the two race for incoming frames.
        """
        return await asyncio.wait_for(self._recv(), timeout=timeout)

    async def _heartbeat_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await self.send_heartbeat()
        except asyncio.CancelledError:
            return
        except websockets.exceptions.ConnectionClosed:
            return

    async def _receive_loop(self) -> None:
        try:
            while True:
                envelope = await self._recv()
                await self._handle(envelope)
        except websockets.exceptions.ConnectionClosed:
            return
        except asyncio.CancelledError:
            return

    async def _handle(self, envelope: Envelope) -> None:
        if envelope.message_type is MessageType.COMMAND:
            await self._handle_command(envelope)
        elif envelope.message_type is MessageType.PING:
            ping = PingPayload.model_validate(envelope.payload)
            await self._send(
                Envelope(
                    protocol_version=envelope.protocol_version,
                    message_type=MessageType.PONG,
                    payload=PongPayload(sent_at=ping.sent_at).model_dump(mode="json"),
                )
            )
        # WELCOME/PONG/ERROR/MESSAGE_ACK/GOODBYE/LOG/EVENT: recorded only, no reaction needed.

    async def _handle_command(self, envelope: Envelope) -> None:
        payload = CommandPayload.model_validate(envelope.payload)
        if not self.respond_to_commands:
            return

        if self.reply_delay:
            await asyncio.sleep(self.reply_delay)
        if self.drop_next_ack:
            self.drop_next_ack = False
        else:
            await self._send(
                Envelope(
                    protocol_version=envelope.protocol_version,
                    message_type=MessageType.COMMAND_ACK,
                    payload=CommandAckPayload(command_id=payload.command_id).model_dump(
                        mode="json"
                    ),
                )
            )

        if self.handler_delay:
            await asyncio.sleep(self.handler_delay)

        try:
            result_data = self._execute(payload.command_type, payload.arguments)
            success, result, error_message = True, result_data, None
        except _UnknownCommand as error:
            success, result, error_message = False, None, str(error)

        result_envelope = Envelope(
            protocol_version=envelope.protocol_version,
            message_type=MessageType.COMMAND_RESULT,
            payload=CommandResultPayload(
                command_id=payload.command_id,
                success=success,
                result=result,
                error_message=error_message,
            ).model_dump(mode="json"),
        )
        if self.drop_next_result:
            self.drop_next_result = False
            return
        await self._send(result_envelope)
        if self.duplicate_next_result:
            self.duplicate_next_result = False
            await self._send(result_envelope)

    def _execute(self, command_type: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Reproduce the real agent's four Phase 2 built-in handlers, no more."""
        if command_type == "system.echo":
            return dict(arguments)
        if command_type == "system.ping":
            return {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
                "agent_version": self.agent_version,
            }
        if command_type == "system.capabilities":
            return {
                "capabilities": list(self.capabilities),
                "command_handlers": list(SUPPORTED_COMMAND_TYPES),
            }
        if command_type == "system.health":
            return {"state": "HEALTHY", "checks": []}
        raise _UnknownCommand(f"Unknown command type: {command_type}")

    async def _teardown(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._receive_task is not None:
            self._receive_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._receive_task
            self._receive_task = None
        if self.connection is not None:
            with suppress(Exception):
                await self.connection.close()
        self.connection = None

    async def _send(self, envelope: Envelope) -> None:
        if self.connection is None:
            raise FakeAgentError("Not connected")
        self.sent.append(envelope)
        await self.connection.send(serialize(envelope))

    async def _recv(self) -> Envelope:
        if self.connection is None:
            raise FakeAgentError("Not connected")
        raw = await self.connection.recv()
        envelope = deserialize(raw)
        self.received.append(envelope)
        return envelope
