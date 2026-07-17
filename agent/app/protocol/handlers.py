"""Pure envelope construction/parsing for the messages this phase cares about.

No network I/O and no business logic here — building an envelope just shapes
a payload model into the wire format; parsing just validates ``payload`` back
into its typed model. Sending/receiving bytes is ``app.connection``'s job;
routing a parsed envelope to a handler is ``app.dispatcher``'s job.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from shared.protocol.message_types import MessageType
from shared.protocol.schemas import (
    Envelope,
    ErrorPayload,
    GoodbyePayload,
    HelloPayload,
    PingPayload,
    PongPayload,
    WelcomePayload,
)


def build_hello(
    *,
    protocol_version: int,
    token: str,
    agent_version: str,
    capabilities: Sequence[str] = (),
) -> Envelope:
    """Build the HELLO envelope the agent sends to authenticate a new connection."""
    payload = HelloPayload(
        token=token, agent_version=agent_version, capabilities=list(capabilities)
    )
    return Envelope(
        protocol_version=protocol_version,
        message_type=MessageType.HELLO,
        payload=payload.model_dump(mode="json"),
    )


def parse_welcome(envelope: Envelope) -> WelcomePayload:
    """Parse the server's handshake acknowledgement."""
    return WelcomePayload.model_validate(envelope.payload)


def build_ping(*, protocol_version: int) -> Envelope:
    """Build a PING envelope for an agent-initiated heartbeat."""
    payload = PingPayload(sent_at=datetime.now(UTC))
    return Envelope(
        protocol_version=protocol_version,
        message_type=MessageType.PING,
        payload=payload.model_dump(mode="json"),
    )


def parse_ping(envelope: Envelope) -> PingPayload:
    """Parse a server-initiated liveness probe."""
    return PingPayload.model_validate(envelope.payload)


def build_pong(*, protocol_version: int, ping: PingPayload) -> Envelope:
    """Build the PONG reply to a server-initiated PING, echoing its ``sent_at``."""
    payload = PongPayload(sent_at=ping.sent_at)
    return Envelope(
        protocol_version=protocol_version,
        message_type=MessageType.PONG,
        payload=payload.model_dump(mode="json"),
    )


def parse_pong(envelope: Envelope) -> PongPayload:
    """Parse the server's reply to an agent-initiated PING."""
    return PongPayload.model_validate(envelope.payload)


def parse_error(envelope: Envelope) -> ErrorPayload:
    """Parse an application-level protocol error reported by the server."""
    return ErrorPayload.model_validate(envelope.payload)


def build_goodbye(*, protocol_version: int, reason: str | None = None) -> Envelope:
    """Build a graceful, agent-initiated disconnect notice."""
    payload = GoodbyePayload(reason=reason)
    return Envelope(
        protocol_version=protocol_version,
        message_type=MessageType.GOODBYE,
        payload=payload.model_dump(mode="json"),
    )


def parse_goodbye(envelope: Envelope) -> GoodbyePayload:
    """Parse a server-initiated disconnect notice."""
    return GoodbyePayload.model_validate(envelope.payload)
