"""Protocol version negotiation and message types — re-exported from ``shared.protocol``.

The canonical definitions live in ``shared/protocol/`` so the cloud server and
the Raspberry Pi agent share exactly one source of truth for the wire format.
This module keeps the original ``app.websocket.protocol`` import path working
for every existing caller in the gateway and its tests.
"""

from __future__ import annotations

from shared.protocol.message_types import (
    ACK_REQUIRED_MESSAGE_TYPES,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    MessageType,
    negotiate_protocol_version,
)

__all__ = [
    "ACK_REQUIRED_MESSAGE_TYPES",
    "PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "MessageType",
    "negotiate_protocol_version",
]
