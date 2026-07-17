"""Envelope (de)serialization; no raw dict manipulation anywhere else in a transport."""

from __future__ import annotations

from pydantic import ValidationError

from shared.protocol.exceptions import ProtocolViolationError
from shared.protocol.schemas import Envelope


def serialize(envelope: Envelope) -> str:
    """Render one envelope as the exact JSON text sent over the wire."""
    return envelope.model_dump_json()


def deserialize(raw: str | bytes) -> Envelope:
    """Parse and validate raw wire data into an ``Envelope``.

    Any structural or type failure — an unrecognized ``message_type``, a
    missing required field, or malformed JSON — raises the same
    ``ProtocolViolationError`` rather than leaking a pydantic/JSON exception
    into the caller.
    """
    try:
        return Envelope.model_validate_json(raw)
    except ValidationError as error:
        raise ProtocolViolationError(f"Invalid message envelope: {error}") from error
