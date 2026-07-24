"""Owns every interactive PTY session on this device.

Real streaming, not request/reply: PTY output is pushed to the server the
moment it's readable (``loop.add_reader``, no polling, no buffering-until-exit)
and PTY input is written the moment a ``TERMINAL_INPUT`` envelope arrives —
this is what lets ``tail -f``/``top``/``vim``/a Python REPL work exactly as
they would over SSH.

Deliberately not a ``CommandHandler``: a terminal session is a persistent,
bidirectional stream with its own lifecycle, not the one-shot
validate/execute/result request the Command Framework's ack/timeout/retry
machinery was built for (see ``docs/agent/TERMINAL.md``). ``TERMINAL_*``
envelopes are instead registered directly on the agent's ``MessageDispatcher``
(``app/lifecycle/factory.py``), bypassing ``app/commands/`` entirely — the
same generic, message-type-keyed routing table ``PING``/``PONG`` already use.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

import structlog

from app.config.settings import AgentSettings
from app.plugins.terminal.metrics import (
    TERMINAL_SESSION_ERRORS_TOTAL,
    TERMINAL_SESSIONS_ACTIVE,
    TERMINAL_SESSIONS_CLOSED_TOTAL,
    TERMINAL_SESSIONS_OPENED_TOTAL,
)
from app.plugins.terminal.pty_process import SpawnedPty, resize_pty, spawn_pty, terminate_pty
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import (
    Envelope,
    TerminalClosedPayload,
    TerminalClosePayload,
    TerminalErrorPayload,
    TerminalInputPayload,
    TerminalOpenedPayload,
    TerminalOpenPayload,
    TerminalOutputPayload,
    TerminalResizePayload,
)

logger = structlog.get_logger(__name__)

Sender = Callable[[Envelope], Awaitable[None]]

#: Bytes read per readable-fd wakeup — generous enough for a full-screen
#: redraw (vim, htop) in one shot, small enough to never noticeably delay
#: encoding/sending it.
_READ_CHUNK_SIZE = 65536

#: How often the idle-timeout watchdog re-checks every open session.
_WATCHDOG_INTERVAL_SECONDS = 5.0


@dataclass
class _Session:
    session_id: UUID
    spawned: SpawnedPty
    last_activity: float = field(default_factory=time.monotonic)
    write_buffer: bytearray = field(default_factory=bytearray)


class TerminalService:
    """Opens, feeds, resizes, and tears down every PTY session on this device."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        send: Sender,
        watchdog_interval_seconds: float = _WATCHDOG_INTERVAL_SECONDS,
    ) -> None:
        self._settings = settings
        self._send = send
        self._watchdog_interval_seconds = watchdog_interval_seconds
        self._sessions: dict[UUID, _Session] = {}
        self._watchdog_task: asyncio.Task[None] | None = None

    @property
    def active_session_count(self) -> int:
        """Number of currently open PTY sessions."""
        return len(self._sessions)

    def start_watchdog(self) -> None:
        """Start the idle-timeout sweep; called once from ``TerminalPlugin.on_startup``."""
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.get_running_loop().create_task(self._watchdog_loop())

    async def shutdown(self) -> None:
        """Terminate every open session and stop the watchdog; called on agent shutdown."""
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None
        for session_id in list(self._sessions):
            await self._close_session(session_id, reason="agent_shutdown")

    # --- MessageDispatcher-registered handlers ------------------------------

    async def handle_open(self, envelope: Envelope) -> None:
        """Open a new PTY session, or confirm an already-open one, for ``TERMINAL_OPEN``."""
        payload = TerminalOpenPayload.model_validate(envelope.payload)
        if not self._settings.terminal_enabled:
            await self._send_error(
                payload.session_id,
                "terminal_disabled",
                "Terminal access is disabled on this device",
            )
            return
        if payload.session_id in self._sessions:
            # A second attach to an already-open session (another browser
            # tab, or a client replaying its own open) — reuse it rather
            # than spawning a second shell for the same session_id.
            await self._send_opened(payload.session_id)
            return
        if len(self._sessions) >= self._settings.terminal_max_sessions_per_device:
            await self._send_error(
                payload.session_id,
                "max_sessions_reached",
                "This device already has the maximum number of open terminal sessions",
            )
            return
        try:
            spawned = spawn_pty(self._settings.terminal_shell, cols=payload.cols, rows=payload.rows)
        except OSError as error:
            TERMINAL_SESSION_ERRORS_TOTAL.inc()
            logger.warning("terminal.spawn_failed", error=str(error))
            await self._send_error(
                payload.session_id, "spawn_failed", "Failed to start a shell on this device"
            )
            return
        session = _Session(session_id=payload.session_id, spawned=spawned)
        self._sessions[payload.session_id] = session
        asyncio.get_running_loop().add_reader(
            spawned.master_fd, self._on_readable, payload.session_id
        )
        TERMINAL_SESSIONS_ACTIVE.set(len(self._sessions))
        TERMINAL_SESSIONS_OPENED_TOTAL.inc()
        logger.info("terminal.opened", session_id=str(payload.session_id))
        await self._send_opened(payload.session_id)

    async def handle_input(self, envelope: Envelope) -> None:
        """Write raw input bytes to the PTY's stdin for ``TERMINAL_INPUT``."""
        payload = TerminalInputPayload.model_validate(envelope.payload)
        session = self._sessions.get(payload.session_id)
        if session is None:
            return
        session.last_activity = time.monotonic()
        self._write(session, payload.data.encode("utf-8", errors="replace"))

    async def handle_resize(self, envelope: Envelope) -> None:
        """Apply a new window size for ``TERMINAL_RESIZE``."""
        payload = TerminalResizePayload.model_validate(envelope.payload)
        session = self._sessions.get(payload.session_id)
        if session is None:
            return
        session.last_activity = time.monotonic()
        with contextlib.suppress(OSError):
            resize_pty(session.spawned.master_fd, cols=payload.cols, rows=payload.rows)

    async def handle_close(self, envelope: Envelope) -> None:
        """Terminate one session on explicit request for ``TERMINAL_CLOSE``."""
        payload = TerminalClosePayload.model_validate(envelope.payload)
        await self._close_session(payload.session_id, reason=payload.reason or "closed_by_client")

    # --- internal ------------------------------------------------------------

    def _write(self, session: _Session, data: bytes) -> None:
        """Write to the PTY master, deferring any unwritten remainder via ``add_writer``.

        The master fd is non-blocking; a full kernel pty buffer (rare for
        keystroke-sized input, but possible for a large paste) raises
        ``BlockingIOError`` rather than stalling the event loop.
        """
        buffer_was_empty = not session.write_buffer
        session.write_buffer.extend(data)
        if buffer_was_empty:
            self._drain_write_buffer(session)

    def _drain_write_buffer(self, session: _Session) -> None:
        loop = asyncio.get_running_loop()
        try:
            written = os.write(session.spawned.master_fd, bytes(session.write_buffer))
            del session.write_buffer[:written]
        except BlockingIOError:
            pass
        except OSError as error:
            logger.warning(
                "terminal.write_failed", session_id=str(session.session_id), error=str(error)
            )
            session.write_buffer.clear()
            with contextlib.suppress(ValueError):
                loop.remove_writer(session.spawned.master_fd)
            return
        if session.write_buffer:
            loop.add_writer(session.spawned.master_fd, self._drain_write_buffer, session)
        else:
            with contextlib.suppress(ValueError):
                loop.remove_writer(session.spawned.master_fd)

    def _on_readable(self, session_id: UUID) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        try:
            data = os.read(session.spawned.master_fd, _READ_CHUNK_SIZE)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            asyncio.ensure_future(self._close_session(session_id, reason="shell_exited"))
            return
        session.last_activity = time.monotonic()
        asyncio.ensure_future(self._push_output(session_id, data))

    async def _push_output(self, session_id: UUID, data: bytes) -> None:
        with contextlib.suppress(Exception):
            await self._send(
                Envelope(
                    protocol_version=self._settings.protocol_version,
                    message_type=MessageType.TERMINAL_OUTPUT,
                    payload=TerminalOutputPayload(
                        session_id=session_id, data=data.decode("utf-8", errors="replace")
                    ).model_dump(mode="json"),
                )
            )

    async def _send_opened(self, session_id: UUID) -> None:
        with contextlib.suppress(Exception):
            await self._send(
                Envelope(
                    protocol_version=self._settings.protocol_version,
                    message_type=MessageType.TERMINAL_OPENED,
                    payload=TerminalOpenedPayload(
                        session_id=session_id, shell=self._settings.terminal_shell
                    ).model_dump(mode="json"),
                )
            )

    async def _send_error(self, session_id: UUID | None, code: str, message: str) -> None:
        with contextlib.suppress(Exception):
            await self._send(
                Envelope(
                    protocol_version=self._settings.protocol_version,
                    message_type=MessageType.TERMINAL_ERROR,
                    payload=TerminalErrorPayload(
                        session_id=session_id, code=code, message=message
                    ).model_dump(mode="json"),
                )
            )

    async def _close_session(self, session_id: UUID, *, reason: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        loop = asyncio.get_running_loop()
        with contextlib.suppress(ValueError):
            loop.remove_reader(session.spawned.master_fd)
        with contextlib.suppress(ValueError):
            loop.remove_writer(session.spawned.master_fd)
        exit_code = await loop.run_in_executor(None, terminate_pty, session.spawned)
        TERMINAL_SESSIONS_ACTIVE.set(len(self._sessions))
        TERMINAL_SESSIONS_CLOSED_TOTAL.inc()
        logger.info("terminal.closed", session_id=str(session_id), reason=reason)
        with contextlib.suppress(Exception):
            await self._send(
                Envelope(
                    protocol_version=self._settings.protocol_version,
                    message_type=MessageType.TERMINAL_CLOSED,
                    payload=TerminalClosedPayload(
                        session_id=session_id, reason=reason, exit_code=exit_code
                    ).model_dump(mode="json"),
                )
            )

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(self._watchdog_interval_seconds)
            now = time.monotonic()
            timed_out = [
                session_id
                for session_id, session in self._sessions.items()
                if now - session.last_activity > self._settings.terminal_session_timeout
            ]
            for session_id in timed_out:
                logger.info("terminal.session_timeout", session_id=str(session_id))
                await self._close_session(session_id, reason="idle_timeout")
