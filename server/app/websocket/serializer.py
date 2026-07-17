"""Envelope (de)serialization — re-exported from ``shared.protocol``.

No raw dict manipulation anywhere else in the gateway. The logic lives in
``shared/protocol/serializer.py`` so the cloud server and the Raspberry Pi
agent share exactly one source of truth.
"""

from __future__ import annotations

from shared.protocol.serializer import deserialize, serialize

__all__ = ["deserialize", "serialize"]
