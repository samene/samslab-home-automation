"""Tests for the envelope/payload schemas and the serializer that wraps them."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.websocket.exceptions import ProtocolViolationError
from app.websocket.protocol import MessageType
from app.websocket.schemas import (
    Envelope,
    HelloPayload,
    MessageAckPayload,
)
from app.websocket.serializer import deserialize, serialize


def test_envelope_round_trips_through_serialize_and_deserialize() -> None:
    """A well-formed envelope serializes and deserializes back to an equal value."""
    envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.PING,
        payload={"sent_at": "2026-01-01T00:00:00Z"},
        correlation_id=uuid4(),
        trace_id="trace-1",
    )
    raw = serialize(envelope)
    restored = deserialize(raw)
    assert restored.message_id == envelope.message_id
    assert restored.message_type is MessageType.PING
    assert restored.correlation_id == envelope.correlation_id
    assert restored.trace_id == "trace-1"


def test_deserialize_rejects_malformed_json() -> None:
    """Malformed JSON raises the gateway's own protocol violation, not a raw json error."""
    with pytest.raises(ProtocolViolationError):
        deserialize("not json at all")


def test_deserialize_rejects_an_unknown_message_type() -> None:
    """An envelope with an unrecognized ``message_type`` fails validation."""
    with pytest.raises(ProtocolViolationError):
        deserialize('{"protocol_version": 1, "message_type": "NOT_A_TYPE", "payload": {}}')


def test_deserialize_rejects_a_missing_required_field() -> None:
    """An envelope missing ``protocol_version`` fails validation."""
    with pytest.raises(ProtocolViolationError):
        deserialize('{"message_type": "PING", "payload": {}}')


def test_envelope_rejects_unknown_top_level_fields() -> None:
    """Envelope forbids extra fields, keeping the wire shape exact."""
    with pytest.raises(ValidationError):
        Envelope.model_validate(
            {
                "protocol_version": 1,
                "message_type": "PING",
                "payload": {},
                "unexpected_field": "nope",
            }
        )


def test_hello_payload_requires_a_non_empty_token() -> None:
    """An empty token fails HelloPayload validation."""
    with pytest.raises(ValidationError):
        HelloPayload(token="", agent_version="1.0.0")


def test_hello_payload_accepts_optional_capabilities_and_resume_cursor() -> None:
    """Capabilities and a resume cursor are optional but preserved when given."""
    hello = HelloPayload(
        token="tok",
        agent_version="1.0.0",
        capabilities=["camera", "gpio"],
        resume_cursor="cursor-123",
    )
    assert hello.capabilities == ["camera", "gpio"]
    assert hello.resume_cursor == "cursor-123"


def test_message_ack_payload_requires_the_acknowledged_message_id() -> None:
    """A MESSAGE_ACK payload without the acknowledged ID fails validation."""
    with pytest.raises(ValidationError):
        MessageAckPayload.model_validate({})


def test_serialize_produces_valid_wire_json() -> None:
    """Serializing produces text that deserialize can parse back unmodified."""
    envelope = Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    assert deserialize(serialize(envelope)).message_type is MessageType.GOODBYE
