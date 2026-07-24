"""Transport-only failures for the browser-facing terminal WebSocket.

Same rationale as ``app/websocket/exceptions.py``: these map to a WebSocket
close code in ``router.py`` and are never seen by REST controllers or the
``ApplicationError`` hierarchy — this transport is not a domain.
"""

from __future__ import annotations


class TerminalGatewayError(Exception):
    """Base error for every terminal WebSocket failure."""


class AuthenticationFailedError(TerminalGatewayError):
    """Raised when HELLO credentials are missing, invalid, or lack terminal permission."""


class HandshakeTimeoutError(TerminalGatewayError):
    """Raised when no HELLO message arrives within the configured handshake window."""


class DeviceUnavailableError(TerminalGatewayError):
    """Raised when the target device doesn't exist, is disabled, or has no open agent session."""


class ProtocolViolationError(TerminalGatewayError):
    """Raised when a received message is malformed or arrives out of order."""


__all__ = [
    "AuthenticationFailedError",
    "DeviceUnavailableError",
    "HandshakeTimeoutError",
    "ProtocolViolationError",
    "TerminalGatewayError",
]
