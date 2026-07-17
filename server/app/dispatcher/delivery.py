"""Delivering one command envelope to a connected device through the WebSocket Gateway.

This module only checks connectivity and hands a message to
``SessionManager.send`` — it never inspects ``command_type``/``payload``
beyond forwarding them as opaque values, and never touches a repository.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.dispatcher.exceptions import DeliveryFailedError
from app.dispatcher.interfaces import DeviceSessionPort
from app.dispatcher.queue import QueuedCommand
from app.websocket.exceptions import BackpressureExceededError
from app.websocket.protocol import PROTOCOL_VERSION, MessageType
from app.websocket.schemas import CommandPayload, Envelope
from app.websocket.session import ConnectionState


class DeliveryService:
    """Check device connectivity and hand a COMMAND envelope to its session."""

    def __init__(self, *, session_manager: DeviceSessionPort) -> None:
        """Bind to the shared, per-application ``SessionManager``."""
        self._session_manager = session_manager

    def is_device_connected(self, device_id: UUID) -> bool:
        """Return whether a device currently holds an open WebSocket session."""
        session = self._session_manager.get(device_id)
        return session is not None and session.connection_state is ConnectionState.OPEN

    async def send_command(self, item: QueuedCommand) -> bool:
        """Enqueue one COMMAND envelope for delivery; return whether it was queued.

        A device with no session at all is reported as a plain failed send
        (the ordinary, expected "not connected" case). A connected device
        whose outgoing queue is full (backpressure) is different enough to
        warrant its own signal, so it raises ``DeliveryFailedError`` instead.
        """
        envelope = _build_command_envelope(item.command_id, item.command_type, item.payload)
        try:
            return self._session_manager.send(item.device_id, envelope)
        except BackpressureExceededError as error:
            raise DeliveryFailedError(
                f"Outgoing queue full for device '{item.device_id}'"
            ) from error


def _build_command_envelope(
    command_id: UUID, command_type: str, arguments: dict[str, Any]
) -> Envelope:
    """Build the outgoing COMMAND envelope for one queued command."""
    return Envelope(
        protocol_version=PROTOCOL_VERSION,
        message_type=MessageType.COMMAND,
        payload=CommandPayload(
            command_id=command_id, command_type=command_type, arguments=arguments
        ).model_dump(mode="json"),
    )
