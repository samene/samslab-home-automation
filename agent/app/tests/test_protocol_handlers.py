"""Tests for pure protocol envelope construction/parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.protocol.handlers import (
    build_goodbye,
    build_hello,
    build_ping,
    build_pong,
    parse_error,
    parse_goodbye,
    parse_ping,
    parse_pong,
    parse_welcome,
)
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import (
    Envelope,
    ErrorPayload,
    GoodbyePayload,
    PingPayload,
    WelcomePayload,
)


def test_build_hello_has_expected_shape() -> None:
    """build_hello produces a HELLO envelope carrying the token and capabilities."""
    envelope = build_hello(
        protocol_version=1, token="secret", agent_version="0.1.0", capabilities=["gpio"]
    )
    assert envelope.message_type is MessageType.HELLO
    assert envelope.protocol_version == 1
    assert envelope.payload["token"] == "secret"
    assert envelope.payload["agent_version"] == "0.1.0"
    assert envelope.payload["capabilities"] == ["gpio"]


def test_build_hello_defaults_to_no_capabilities() -> None:
    """capabilities defaults to an empty list when omitted."""
    envelope = build_hello(protocol_version=1, token="secret", agent_version="0.1.0")
    assert envelope.payload["capabilities"] == []


def test_parse_welcome_roundtrips() -> None:
    """parse_welcome recovers the typed payload from an envelope."""
    session_id = uuid4()
    welcome = WelcomePayload(
        session_id=session_id,
        server_time=datetime.now(UTC),
        protocol_version=1,
        heartbeat_interval_seconds=30.0,
        heartbeat_timeout_seconds=10.0,
    )
    envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.WELCOME,
        payload=welcome.model_dump(mode="json"),
    )

    parsed = parse_welcome(envelope)

    assert parsed.session_id == session_id


def test_build_and_parse_ping() -> None:
    """build_ping produces a PING envelope parse_ping can read back."""
    envelope = build_ping(protocol_version=1)
    assert envelope.message_type is MessageType.PING
    parsed = parse_ping(envelope)
    assert parsed.sent_at is not None


def test_build_pong_echoes_ping_sent_at() -> None:
    """build_pong's payload echoes the originating ping's sent_at."""
    sent_at = datetime.now(UTC)
    ping = PingPayload(sent_at=sent_at)

    envelope = build_pong(protocol_version=1, ping=ping)

    assert envelope.message_type is MessageType.PONG
    parsed = parse_pong(envelope)
    assert parsed.sent_at == sent_at


def test_parse_error() -> None:
    """parse_error recovers code/message/details."""
    payload = ErrorPayload(code="E1", message="boom", details={"a": 1})
    envelope = Envelope(
        protocol_version=1, message_type=MessageType.ERROR, payload=payload.model_dump(mode="json")
    )

    parsed = parse_error(envelope)

    assert parsed.code == "E1"
    assert parsed.message == "boom"
    assert parsed.details == {"a": 1}


def test_build_and_parse_goodbye_with_reason() -> None:
    """build_goodbye/parse_goodbye roundtrip a reason string."""
    envelope = build_goodbye(protocol_version=1, reason="shutting down")
    assert envelope.message_type is MessageType.GOODBYE

    parsed = parse_goodbye(envelope)

    assert parsed.reason == "shutting down"


def test_parse_goodbye_without_reason() -> None:
    """A GOODBYE with no reason parses to None."""
    payload = GoodbyePayload()
    envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.GOODBYE,
        payload=payload.model_dump(mode="json"),
    )

    parsed = parse_goodbye(envelope)

    assert parsed.reason is None
