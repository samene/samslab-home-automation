"""Transport-only failures for the agent's connection to the server."""

from __future__ import annotations


class ConnectionManagerError(Exception):
    """Base error for every connection-manager failure."""


class AuthenticationRejectedError(ConnectionManagerError):
    """Raised when the server's handshake reply isn't the expected WELCOME."""


class DeviceTokenRequestError(ConnectionManagerError):
    """Raised when exchanging a signed assertion for a device access token fails.

    Covers network failures, a non-2xx response, and a malformed response
    body alike — the caller (``ConnectionManager.authenticate``) treats this
    the same way it treats a rejected HELLO, retrying with backoff via the
    orchestrator's existing broad ``except Exception``.
    """


class NotConnectedError(ConnectionManagerError):
    """Raised when send/receive is attempted with no open transport."""
