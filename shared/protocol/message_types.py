"""Protocol version negotiation and the fixed set of WebSocket message types."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from shared.protocol.exceptions import ProtocolVersionUnsupportedError

#: The version this protocol currently speaks by default.
PROTOCOL_VERSION: Final[int] = 1

#: Every protocol version either side can negotiate down to. A future version
#: bump adds to this set rather than replacing it, so older agents keep working.
SUPPORTED_PROTOCOL_VERSIONS: Final[frozenset[int]] = frozenset({1})


class MessageType(StrEnum):
    """Every message type this protocol defines."""

    HELLO = "HELLO"
    WELCOME = "WELCOME"
    PING = "PING"
    PONG = "PONG"
    COMMAND = "COMMAND"
    COMMAND_ACK = "COMMAND_ACK"
    COMMAND_RESULT = "COMMAND_RESULT"
    EVENT = "EVENT"
    LOG = "LOG"
    ERROR = "ERROR"
    MESSAGE_ACK = "MESSAGE_ACK"
    GOODBYE = "GOODBYE"


#: Message types whose delivery is tracked for acknowledgement, retry, and timeout.
ACK_REQUIRED_MESSAGE_TYPES: Final[frozenset[MessageType]] = frozenset(
    {
        MessageType.COMMAND,
        MessageType.COMMAND_RESULT,
        MessageType.EVENT,
        MessageType.LOG,
    }
)


def negotiate_protocol_version(requested: int) -> int:
    """Return the protocol version to use for a connection, or fail if unsupported.

    Only one version exists today, but future versions can be added to
    ``SUPPORTED_PROTOCOL_VERSIONS`` and negotiated without breaking older agents.
    """
    if requested not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ProtocolVersionUnsupportedError(
            f"Protocol version {requested} is not supported; "
            f"supported versions: {sorted(SUPPORTED_PROTOCOL_VERSIONS)}"
        )
    return requested
