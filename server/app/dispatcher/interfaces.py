"""Structural (``Protocol``) contracts the dispatcher's submodules depend on.

Defined here, not imported from a concrete class, so ``delivery.py``,
``ack_manager.py``, ``timeouts.py``, ``result_handler.py``, and ``worker.py``
never import ``dispatcher.py`` (the composition root that constructs and
wires all of them) — that would be circular. Both ``CommandApplicationService``
and ``SessionManager`` already satisfy these Protocols structurally; nothing
about them needs to change to conform.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.application.dto.command_dto import CommandDetailDTO
from app.dispatcher.queue import QueuedCommand
from app.websocket.schemas import Envelope
from app.websocket.session import Session


class CommandLifecyclePort(Protocol):
    """The Command lifecycle operations the dispatcher needs, each its own transaction."""

    async def list_pending(self, *, limit: int) -> list[CommandDetailDTO]:
        """Return commands awaiting dispatch, highest priority and oldest first."""
        ...

    async def mark_dispatched(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record that a command has been handed to a transport; ``None`` if not applicable."""
        ...

    async def mark_running(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record that execution started on the device; ``None`` if not applicable."""
        ...

    async def mark_timeout(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record that a command never produced a result in time; ``None`` if not applicable."""
        ...

    async def record_retry(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record one more redelivery attempt; ``None`` if not applicable."""
        ...

    async def complete_command(
        self, command_id: UUID, *, result: dict[str, Any]
    ) -> CommandDetailDTO | None:
        """Record a successful terminal outcome; ``None`` if not applicable."""
        ...

    async def fail_command(
        self, command_id: UUID, *, error_message: str
    ) -> CommandDetailDTO | None:
        """Record a failed terminal outcome; ``None`` if not applicable."""
        ...


class DeviceSessionPort(Protocol):
    """The subset of ``SessionManager`` the dispatcher needs to deliver a message."""

    def get(self, device_id: UUID) -> Session | None:
        """Return the device's current session, or ``None`` if not connected."""
        ...

    def send(self, device_id: UUID, envelope: Envelope) -> bool:
        """Queue one message for a connected device; return whether it was queued."""
        ...


class CommandDeliveryPort(Protocol):
    """The ``DeliveryService`` operations ``worker.py``/``ack_manager.py`` depend on."""

    def is_device_connected(self, device_id: UUID) -> bool:
        """Return whether a device currently holds an open WebSocket session."""
        ...

    async def send_command(self, item: QueuedCommand) -> bool:
        """Enqueue one COMMAND envelope for delivery; return whether it was queued."""
        ...
