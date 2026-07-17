"""Token-related failure injection: expired and malformed credentials.

Transport-level failure injection (disconnect, latency, duplicate packets,
lost ACK, a slow handler) lives on ``FakeAgent`` itself
(``tests/fakes/fake_agent.py``) — those need a live connection to act on,
while these only need a JWT codec.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from tests.utils.server_harness import ServerHarness

#: A token that is not, and never was, validly signed or structured.
MALFORMED_TOKEN = "this-is-not-a-real-jwt-token"  # noqa: S105


#: Well beyond any configured JWT clock-skew leeway (default 30s), so this is
#: unambiguously expired rather than borderline-valid under skew tolerance.
_SAFELY_EXPIRED = timedelta(hours=1)


def expired_device_token(server: ServerHarness, device_id: UUID) -> str:
    """A device token that is already (unambiguously) expired the moment it's issued."""
    return server.issue_device_token(device_id, expires_in=-_SAFELY_EXPIRED)


def expired_user_token(server: ServerHarness, *, roles: list[str] | None = None) -> str:
    """A user token that is already (unambiguously) expired the moment it's issued."""
    return server.issue_user_token(roles=roles, expires_in=-_SAFELY_EXPIRED)
