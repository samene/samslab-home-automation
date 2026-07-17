"""Tests for protocol version negotiation and the message type catalog."""

from __future__ import annotations

import pytest

from app.websocket.exceptions import ProtocolVersionUnsupportedError
from app.websocket.protocol import (
    ACK_REQUIRED_MESSAGE_TYPES,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    MessageType,
    negotiate_protocol_version,
)


def test_negotiate_protocol_version_accepts_a_supported_version() -> None:
    """The current protocol version negotiates to itself."""
    assert negotiate_protocol_version(PROTOCOL_VERSION) == PROTOCOL_VERSION


def test_negotiate_protocol_version_rejects_an_unsupported_version() -> None:
    """A version outside the supported set fails negotiation."""
    with pytest.raises(ProtocolVersionUnsupportedError):
        negotiate_protocol_version(999)


def test_supported_protocol_versions_includes_the_current_version() -> None:
    """The current protocol version must always be negotiable."""
    assert PROTOCOL_VERSION in SUPPORTED_PROTOCOL_VERSIONS


@pytest.mark.parametrize(
    "message_type",
    [
        MessageType.COMMAND,
        MessageType.COMMAND_RESULT,
        MessageType.EVENT,
        MessageType.LOG,
    ],
)
def test_ack_required_message_types_include_business_payloads(message_type: MessageType) -> None:
    """Every business-carrying message type is tracked for delivery acknowledgement."""
    assert message_type in ACK_REQUIRED_MESSAGE_TYPES


@pytest.mark.parametrize(
    "message_type",
    [MessageType.PING, MessageType.PONG, MessageType.MESSAGE_ACK, MessageType.HELLO],
)
def test_ack_required_message_types_exclude_control_messages(message_type: MessageType) -> None:
    """Control/handshake messages are never themselves tracked for acknowledgement."""
    assert message_type not in ACK_REQUIRED_MESSAGE_TYPES
