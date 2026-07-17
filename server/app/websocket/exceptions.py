"""Transport-only failures for the WebSocket gateway; never a domain exception.

``ProtocolViolationError``/``ProtocolVersionUnsupportedError`` are re-exported
from ``shared.protocol.exceptions`` — the wire-format failures are shared with
the agent, while everything else here is gateway-session-specific and stays
local. These map to a WebSocket close code in ``gateway.py`` and are never
seen by REST controllers or the ``ApplicationError`` hierarchy — the gateway
is not a domain and does not participate in that translation chain.
"""

from __future__ import annotations

from shared.protocol.exceptions import (
    ProtocolVersionUnsupportedError,
    ProtocolViolationError,
)


class WebSocketGatewayError(Exception):
    """Base error for every WebSocket gateway failure."""


class AuthenticationFailedError(WebSocketGatewayError):
    """Raised when HELLO credentials are missing, invalid, or belong to a disabled device."""


class HandshakeTimeoutError(WebSocketGatewayError):
    """Raised when no HELLO message arrives within the configured handshake window."""


class DuplicateSessionError(WebSocketGatewayError):
    """Raised when a device already has an open session."""


class BackpressureExceededError(WebSocketGatewayError):
    """Raised when a connection's bounded outgoing queue is full."""


class GoodbyeReceived(WebSocketGatewayError):
    """Raised to unwind the receive loop after a client-initiated GOODBYE."""


__all__ = [
    "AuthenticationFailedError",
    "BackpressureExceededError",
    "DuplicateSessionError",
    "GoodbyeReceived",
    "HandshakeTimeoutError",
    "ProtocolVersionUnsupportedError",
    "ProtocolViolationError",
    "WebSocketGatewayError",
]
