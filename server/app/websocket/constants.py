"""Fixed WebSocket gateway constants that are not deployment-configurable.

Deployment-tunable values (heartbeat interval, queue size, ack timeout, ...)
live on ``Settings`` instead; only values that would never sensibly vary by
environment belong here.
"""

from __future__ import annotations

from typing import Final

#: Bound on how many recent incoming message IDs one connection remembers for
#: duplicate detection. Oldest entries are evicted once this limit is reached.
MAX_SEEN_MESSAGE_IDS: Final[int] = 1000

#: How often a connection's outgoing-message watchdog sweeps for retry/timeout.
ACK_WATCHDOG_INTERVAL_SECONDS: Final[float] = 1.0


class CloseCode:
    """Application-defined WebSocket close codes (RFC 6455 reserves 4000-4999)."""

    NORMAL_CLOSURE: Final[int] = 1000
    SERVER_SHUTDOWN: Final[int] = 1001
    PROTOCOL_VIOLATION: Final[int] = 4400
    AUTHENTICATION_FAILED: Final[int] = 4401
    DUPLICATE_SESSION: Final[int] = 4409
    HANDSHAKE_TIMEOUT: Final[int] = 4408
    UNSUPPORTED_PROTOCOL_VERSION: Final[int] = 4426
    BACKPRESSURE: Final[int] = 4413
    HEARTBEAT_TIMEOUT: Final[int] = 4000
    #: Used by the browser-facing terminal transport (app/terminal/) when the
    #: target device doesn't exist, is disabled, or has no open agent session.
    DEVICE_UNAVAILABLE: Final[int] = 4404
