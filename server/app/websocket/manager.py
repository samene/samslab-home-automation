"""In-memory registry of one authenticated session per connected device."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.websocket.exceptions import BackpressureExceededError, DuplicateSessionError
from app.websocket.metrics import ACTIVE_SESSIONS, CONNECTED_DEVICES
from app.websocket.schemas import Envelope, SessionSummaryDTO
from app.websocket.session import ConnectionState, Session


def _to_summary(session: Session) -> SessionSummaryDTO:
    """Map a live ``Session`` to the read-only shape admin endpoints expose."""
    return SessionSummaryDTO(
        device_id=session.device_id,
        connection_id=session.connection_id,
        connected_at=session.connected_at,
        last_seen=session.last_seen,
        protocol_version=session.protocol_version,
        agent_version=session.agent_version,
        remote_ip=session.remote_ip,
        connection_state=session.connection_state.value,
        pending_message_count=len(session.pending_messages),
    )


class SessionManager:
    """One in-memory registry shared by every WebSocket connection in this process.

    Never persisted: a server restart drops every session, matching the
    gateway's transport-only responsibility. At most one ``Session`` per
    ``device_id`` is enforced by ``register``.
    """

    def __init__(self) -> None:
        """Start empty; a fresh process always starts with zero connected devices."""
        self._sessions: dict[UUID, Session] = {}
        self._lock = asyncio.Lock()
        self._active_tasks: set[asyncio.Task[None]] = set()

    def track(self, task: asyncio.Task[None]) -> None:
        """Track one connection's own task so shutdown can wait for it to fully finish.

        Closing a session's socket does not by itself guarantee the task
        processing that connection has run its own cleanup (unregistering,
        marking the device offline) — only tracking the task and awaiting it
        lets shutdown avoid disposing shared infrastructure out from under a
        still-finishing connection.
        """
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    @property
    def active_task_count(self) -> int:
        """Number of connection tasks still running, including finally-block cleanup.

        Unlike ``get(device_id) is None`` (true once ``unregister`` runs, but
        *before* any trailing cleanup like marking a device offline), this only
        reaches zero once a connection's task has fully returned.
        """
        return len(self._active_tasks)

    async def wait_closed(self, *, timeout: float = 5.0) -> None:
        """Wait for every tracked connection task to finish, bounded by ``timeout``."""
        tasks = list(self._active_tasks)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()

    async def register(self, session: Session) -> None:
        """Add a newly authenticated session, rejecting a second one for the same device."""
        async with self._lock:
            existing = self._sessions.get(session.device_id)
            if existing is not None and existing.connection_state is ConnectionState.OPEN:
                raise DuplicateSessionError(
                    f"Device '{session.device_id}' already has an open session"
                )
            self._sessions[session.device_id] = session
        self._update_gauges()

    async def unregister(self, device_id: UUID) -> None:
        """Remove a session; a no-op if the device has no tracked session."""
        async with self._lock:
            self._sessions.pop(device_id, None)
        self._update_gauges()

    def get(self, device_id: UUID) -> Session | None:
        """Return the current session for a device, or ``None`` if not connected."""
        return self._sessions.get(device_id)

    def get_summary(self, device_id: UUID) -> SessionSummaryDTO | None:
        """Return one device's read-only session summary, or ``None`` if not connected."""
        session = self._sessions.get(device_id)
        return None if session is None else _to_summary(session)

    def list_sessions(self) -> list[SessionSummaryDTO]:
        """Return a read-only summary of every currently tracked session."""
        return [_to_summary(session) for session in self._sessions.values()]

    def send(self, device_id: UUID, envelope: Envelope) -> bool:
        """Queue one message for a connected device; return whether it was queued."""
        session = self._sessions.get(device_id)
        if session is None:
            return False
        session.connection.enqueue(envelope)
        return True

    def broadcast(self, envelope: Envelope, *, exclude: UUID | None = None) -> int:
        """Queue one message for every connected device except ``exclude``.

        A single slow client's full queue is skipped rather than aborting the
        whole broadcast for every other connected device.
        """
        count = 0
        for session in self._sessions.values():
            if session.device_id == exclude:
                continue
            try:
                session.connection.enqueue(envelope)
            except BackpressureExceededError:
                continue
            count += 1
        return count

    async def disconnect(self, device_id: UUID, *, code: int = 1000, reason: str = "") -> None:
        """Close and forget one device's session."""
        async with self._lock:
            session = self._sessions.pop(device_id, None)
        if session is not None:
            await session.connection.close(code=code, reason=reason)
        self._update_gauges()

    async def close_all(self) -> None:
        """Gracefully close every session; used during application shutdown."""
        for device_id in list(self._sessions.keys()):
            await self.disconnect(device_id, code=1001, reason="server_shutdown")

    def _update_gauges(self) -> None:
        CONNECTED_DEVICES.set(len(self._sessions))
        ACTIVE_SESSIONS.set(len(self._sessions))
