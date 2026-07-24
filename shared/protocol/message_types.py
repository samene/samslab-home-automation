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
    # Interactive terminal session control — carried over the same envelope
    # transport as everything above, but deliberately outside the Command
    # Framework: a terminal is a persistent, bidirectional PTY session, not a
    # one-shot request/reply. TERMINAL_OPEN/TERMINAL_INPUT/TERMINAL_RESIZE/
    # TERMINAL_CLOSE flow toward the agent (from the server, itself relaying
    # from a browser terminal connection — see server/app/terminal/);
    # TERMINAL_OPENED/TERMINAL_OUTPUT/TERMINAL_CLOSED/TERMINAL_ERROR flow back.
    TERMINAL_OPEN = "TERMINAL_OPEN"
    TERMINAL_OPENED = "TERMINAL_OPENED"
    TERMINAL_INPUT = "TERMINAL_INPUT"
    TERMINAL_OUTPUT = "TERMINAL_OUTPUT"
    TERMINAL_RESIZE = "TERMINAL_RESIZE"
    TERMINAL_CLOSE = "TERMINAL_CLOSE"
    TERMINAL_CLOSED = "TERMINAL_CLOSED"
    TERMINAL_ERROR = "TERMINAL_ERROR"


#: Message types whose delivery is tracked for acknowledgement, retry, and timeout.
ACK_REQUIRED_MESSAGE_TYPES: Final[frozenset[MessageType]] = frozenset(
    {
        MessageType.COMMAND,
        MessageType.COMMAND_RESULT,
        MessageType.EVENT,
        MessageType.LOG,
    }
)

#: Terminal messages are deliberately excluded from ack/retry tracking, exactly
#: like PING/PONG — TERMINAL_INPUT/TERMINAL_OUTPUT are a high-frequency,
#: latency-sensitive byte stream (every keystroke, every screen redraw) where
#: transport-level ack/retry would add overhead and out-of-order-redelivery
#: risk without benefit. TCP already guarantees in-order delivery within one
#: connection; a dropped connection is handled by closing and reopening the
#: terminal session, not by per-message retry.
TERMINAL_MESSAGE_TYPES: Final[frozenset[MessageType]] = frozenset(
    {
        MessageType.TERMINAL_OPEN,
        MessageType.TERMINAL_OPENED,
        MessageType.TERMINAL_INPUT,
        MessageType.TERMINAL_OUTPUT,
        MessageType.TERMINAL_RESIZE,
        MessageType.TERMINAL_CLOSE,
        MessageType.TERMINAL_CLOSED,
        MessageType.TERMINAL_ERROR,
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
