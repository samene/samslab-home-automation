"""Failures raised while negotiating or (de)serializing the shared wire protocol.

Distinct from a transport's own session-management failures (e.g. the cloud
server's ``AuthenticationFailedError``/``DuplicateSessionError``, or a future
agent-side connection error) — those are transport concerns and stay in their
own package, subclassing their own base, not this one.
"""

from __future__ import annotations


class ProtocolError(Exception):
    """Base error for every shared-protocol failure."""


class ProtocolViolationError(ProtocolError):
    """Raised when a received message fails envelope or payload validation."""


class ProtocolVersionUnsupportedError(ProtocolError):
    """Raised when a requested protocol version is not in the supported set."""
