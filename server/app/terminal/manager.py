"""In-memory registry of terminal session state per device — never persisted,
exactly like ``app/websocket/manager.py``'s ``SessionManager``: a server
restart drops every tracked terminal session along with every WebSocket
connection, agent and browser alike.

Multiple browser connections may be attached to the same device's session at
once (e.g. two tabs) — output is broadcast to all of them (see
``app/terminal/relay.py``), and the underlying PTY is reused rather than
spawning a second shell, matching "one active session per Raspberry Pi."

A shell that's already running has nothing new to say just because a fresh
browser attached to it — it already printed its prompt once, and won't
reprint it on its own. Without `output_buffer`/`append_output`, a reattach
(the drawer closed and reopened, or a second tab) would show a blank screen
that looks permanently hung even though the session is alive and working;
`router.py` replays the buffered tail directly to just the reattaching
browser (never broadcast) so it has something to show immediately.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.terminal.connection import BrowserConnection

#: Bounded so a long-idle session can't grow this without limit — large
#: enough to give a reattaching browser meaningful context (recent output,
#: the shell's last prompt), small enough to stay cheap to hold per device.
#: See "Output replay on reattach" in docs/agent/TERMINAL.md for why this
#: exists and what it does and doesn't reconstruct.
_MAX_OUTPUT_BUFFER_CHARS = 16384


@dataclass
class _DeviceTerminalState:
    """One device's current terminal session, if any, and who's watching it."""

    session_id: UUID | None = None
    shell: str | None = None
    browsers: set[BrowserConnection] = field(default_factory=set)
    #: The tail of this session's own output, replayed (only to the newly
    #: attaching browser, never broadcast) when a second/later browser
    #: attaches to an already-open session — see `attach`/`output_buffer_for`.
    output_buffer: str = ""


class TerminalSessionManager:
    """Tracks, per device, the current PTY session ID and every attached browser."""

    def __init__(self) -> None:
        self._devices: dict[UUID, _DeviceTerminalState] = {}
        self._lock = asyncio.Lock()

    async def attach(self, device_id: UUID, browser: BrowserConnection) -> tuple[UUID, bool]:
        """Register a browser connection for a device.

        Returns the session's authoritative ID (server-minted, never
        client-supplied — the same reasoning as ``WelcomePayload.session_id``
        on the agent gateway) and whether this call just created a new
        session (``True``) or attached to one already open (``False``).
        """
        async with self._lock:
            state = self._devices.setdefault(device_id, _DeviceTerminalState())
            is_new = state.session_id is None
            session_id = state.session_id if state.session_id is not None else uuid4()
            if is_new:
                state.session_id = session_id
                state.shell = None
                state.output_buffer = ""
            state.browsers.add(browser)
            return session_id, is_new

    async def detach(self, device_id: UUID, browser: BrowserConnection) -> None:
        """Remove a browser connection; a no-op if it was already removed."""
        async with self._lock:
            state = self._devices.get(device_id)
            if state is None:
                return
            state.browsers.discard(browser)

    def mark_opened(self, device_id: UUID, session_id: UUID, shell: str) -> None:
        """Record that the agent confirmed ``session_id`` is open, running ``shell``."""
        state = self._devices.get(device_id)
        if state is None or state.session_id != session_id:
            return
        state.shell = shell

    def mark_closed(self, device_id: UUID, session_id: UUID) -> None:
        """Record that ``session_id`` ended; the next ``attach`` mints a fresh one."""
        state = self._devices.get(device_id)
        if state is None or state.session_id != session_id:
            return
        state.session_id = None
        state.shell = None
        state.output_buffer = ""

    def force_clear(self, device_id: UUID) -> tuple[UUID, frozenset[BrowserConnection]] | None:
        """Unconditionally clear a device's tracked session, whatever it is.

        Unlike ``mark_closed``, this doesn't require knowing which
        ``session_id`` ended — used when the agent's own connection to the
        server drops (crash, network loss, or a graceful shutdown that lost
        the race to send its own ``TERMINAL_CLOSED`` — see
        ``docs/agent/TERMINAL.md``). The PTY lives only in the agent
        process's memory, so no tracked session can possibly still be alive
        once that connection is gone, regardless of whether a clean
        ``TERMINAL_CLOSED`` ever arrived for it.

        Returns the cleared session ID and every browser that was attached
        (so the caller can notify them the session ended), or ``None`` if
        nothing was tracked for this device.
        """
        state = self._devices.get(device_id)
        if state is None or state.session_id is None:
            return None
        session_id = state.session_id
        browsers = frozenset(state.browsers)
        state.session_id = None
        state.shell = None
        state.output_buffer = ""
        return session_id, browsers

    def session_id_for(self, device_id: UUID) -> UUID | None:
        """The currently tracked session ID for a device, or ``None`` if none is open."""
        state = self._devices.get(device_id)
        return state.session_id if state else None

    def shell_for(self, device_id: UUID) -> str | None:
        """The shell an already-open session is running, or ``None`` if not yet confirmed."""
        state = self._devices.get(device_id)
        return state.shell if state else None

    def browsers_for(self, device_id: UUID) -> frozenset[BrowserConnection]:
        """Every browser connection currently attached to a device's session."""
        state = self._devices.get(device_id)
        return frozenset(state.browsers) if state else frozenset()

    def append_output(self, device_id: UUID, data: str) -> None:
        """Record output as it's relayed, so a later reattach has something to replay.

        A no-op if nothing is tracked for this device (e.g. output arriving
        for a session that was already force-cleared) — there's nothing
        meaningful to buffer it against.
        """
        state = self._devices.get(device_id)
        if state is None:
            return
        state.output_buffer += data
        if len(state.output_buffer) > _MAX_OUTPUT_BUFFER_CHARS:
            state.output_buffer = state.output_buffer[-_MAX_OUTPUT_BUFFER_CHARS:]

    def output_buffer_for(self, device_id: UUID) -> str:
        """The tail of a session's own output, for replaying to a reattaching browser."""
        state = self._devices.get(device_id)
        return state.output_buffer if state else ""
