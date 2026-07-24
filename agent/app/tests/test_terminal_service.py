"""Tests for TerminalService: session lifecycle, real PTY I/O streaming, idle timeout.

Uses a real ``/bin/sh`` PTY (see test_terminal_pty_process.py's rationale) and
a fake ``send`` callable that just records every envelope — the same
injection seam ``app/plugins/terminal/service.py`` uses for the real
``ConnectionManager.send``.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.plugins.terminal.service import TerminalService
from app.tests.conftest import make_settings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import (
    Envelope,
    TerminalClosePayload,
    TerminalInputPayload,
    TerminalOpenPayload,
    TerminalResizePayload,
)


class FakeSender:
    """Records every envelope handed to ``send`` in order."""

    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def __call__(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    def of_type(self, message_type: MessageType) -> list[Envelope]:
        return [envelope for envelope in self.sent if envelope.message_type is message_type]


def _open_envelope(session_id: UUID, *, cols: int = 80, rows: int = 24) -> Envelope:
    return Envelope(
        protocol_version=1,
        message_type=MessageType.TERMINAL_OPEN,
        payload=TerminalOpenPayload(session_id=session_id, cols=cols, rows=rows).model_dump(
            mode="json"
        ),
    )


async def _wait_until(predicate: object, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():  # type: ignore[operator]
            return
        await asyncio.sleep(0.02)
    raise AssertionError("Timed out waiting for condition")


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def service(sender: FakeSender) -> TerminalService:
    settings = make_settings(TERMINAL_ENABLED=True, TERMINAL_SHELL="/bin/sh")
    return TerminalService(settings, send=sender)


async def test_handle_open_rejects_when_terminal_disabled(sender: FakeSender) -> None:
    settings = make_settings(TERMINAL_ENABLED=False)
    service = TerminalService(settings, send=sender)
    session_id = uuid4()

    await service.handle_open(_open_envelope(session_id))

    errors = sender.of_type(MessageType.TERMINAL_ERROR)
    assert len(errors) == 1
    assert errors[0].payload["code"] == "terminal_disabled"
    assert service.active_session_count == 0


async def test_handle_open_spawns_a_shell_and_confirms(
    service: TerminalService, sender: FakeSender
) -> None:
    session_id = uuid4()

    await service.handle_open(_open_envelope(session_id))

    opened = sender.of_type(MessageType.TERMINAL_OPENED)
    assert len(opened) == 1
    assert opened[0].payload["session_id"] == str(session_id)
    assert opened[0].payload["shell"] == "/bin/sh"
    assert service.active_session_count == 1

    await service.shutdown()


async def test_handle_open_reuses_an_already_open_session(
    service: TerminalService, sender: FakeSender
) -> None:
    session_id = uuid4()
    await service.handle_open(_open_envelope(session_id))

    await service.handle_open(_open_envelope(session_id))

    assert service.active_session_count == 1
    assert len(sender.of_type(MessageType.TERMINAL_OPENED)) == 2

    await service.shutdown()


async def test_handle_open_rejects_beyond_max_sessions_per_device(sender: FakeSender) -> None:
    settings = make_settings(
        TERMINAL_ENABLED=True, TERMINAL_SHELL="/bin/sh", TERMINAL_MAX_SESSIONS_PER_DEVICE=1
    )
    service = TerminalService(settings, send=sender)
    first_id, second_id = uuid4(), uuid4()
    await service.handle_open(_open_envelope(first_id))

    await service.handle_open(_open_envelope(second_id))

    assert service.active_session_count == 1
    errors = sender.of_type(MessageType.TERMINAL_ERROR)
    assert len(errors) == 1
    assert errors[0].payload["code"] == "max_sessions_reached"

    await service.shutdown()


async def test_input_is_echoed_back_as_output(service: TerminalService, sender: FakeSender) -> None:
    session_id = uuid4()
    await service.handle_open(_open_envelope(session_id))

    await service.handle_input(
        Envelope(
            protocol_version=1,
            message_type=MessageType.TERMINAL_INPUT,
            payload=TerminalInputPayload(
                session_id=session_id, data="echo hello-agent\n"
            ).model_dump(mode="json"),
        )
    )

    def _saw_output() -> bool:
        return any(
            "hello-agent" in envelope.payload["data"]
            for envelope in sender.of_type(MessageType.TERMINAL_OUTPUT)
        )

    await _wait_until(_saw_output)

    await service.shutdown()


async def test_handle_resize_applies_new_window_size(
    service: TerminalService, sender: FakeSender
) -> None:
    session_id = uuid4()
    await service.handle_open(_open_envelope(session_id, cols=80, rows=24))

    await service.handle_resize(
        Envelope(
            protocol_version=1,
            message_type=MessageType.TERMINAL_RESIZE,
            payload=TerminalResizePayload(session_id=session_id, cols=120, rows=40).model_dump(
                mode="json"
            ),
        )
    )

    import fcntl
    import struct
    import termios

    session = service._sessions[session_id]  # noqa: SLF001 - reaching into private state for assertion
    raw = fcntl.ioctl(session.spawned.master_fd, termios.TIOCGWINSZ, b"\x00" * 8)
    rows, cols, _x, _y = struct.unpack("HHHH", raw)
    assert (rows, cols) == (40, 120)

    await service.shutdown()


async def test_handle_close_terminates_the_session_and_confirms(
    service: TerminalService, sender: FakeSender
) -> None:
    session_id = uuid4()
    await service.handle_open(_open_envelope(session_id))

    await service.handle_close(
        Envelope(
            protocol_version=1,
            message_type=MessageType.TERMINAL_CLOSE,
            payload=TerminalClosePayload(session_id=session_id, reason="user_requested").model_dump(
                mode="json"
            ),
        )
    )

    assert service.active_session_count == 0
    closed = sender.of_type(MessageType.TERMINAL_CLOSED)
    assert len(closed) == 1
    assert closed[0].payload["reason"] == "user_requested"


async def test_shell_exit_is_detected_and_reported_as_closed(sender: FakeSender) -> None:
    settings = make_settings(TERMINAL_ENABLED=True, TERMINAL_SHELL="/bin/true")
    service = TerminalService(settings, send=sender)
    session_id = uuid4()

    await service.handle_open(_open_envelope(session_id))

    def _saw_closed() -> bool:
        return len(sender.of_type(MessageType.TERMINAL_CLOSED)) == 1

    await _wait_until(_saw_closed)
    assert sender.of_type(MessageType.TERMINAL_CLOSED)[0].payload["reason"] == "shell_exited"
    assert service.active_session_count == 0


async def test_idle_timeout_closes_the_session(sender: FakeSender) -> None:
    settings = make_settings(
        TERMINAL_ENABLED=True, TERMINAL_SHELL="/bin/sh", TERMINAL_SESSION_TIMEOUT=0.05
    )
    service = TerminalService(settings, send=sender, watchdog_interval_seconds=0.05)
    service.start_watchdog()
    session_id = uuid4()
    await service.handle_open(_open_envelope(session_id))

    def _saw_timeout_closed() -> bool:
        closed = sender.of_type(MessageType.TERMINAL_CLOSED)
        return any(envelope.payload["reason"] == "idle_timeout" for envelope in closed)

    await _wait_until(_saw_timeout_closed, timeout=3.0)
    assert service.active_session_count == 0

    await service.shutdown()


async def test_shutdown_terminates_every_open_session(sender: FakeSender) -> None:
    settings = make_settings(
        TERMINAL_ENABLED=True, TERMINAL_SHELL="/bin/sh", TERMINAL_MAX_SESSIONS_PER_DEVICE=2
    )
    service = TerminalService(settings, send=sender)
    await service.handle_open(_open_envelope(uuid4()))
    await service.handle_open(_open_envelope(uuid4(), cols=100, rows=30))
    assert service.active_session_count == 2

    await service.shutdown()

    assert service.active_session_count == 0
    closed = sender.of_type(MessageType.TERMINAL_CLOSED)
    assert len(closed) == 2
    assert all(envelope.payload["reason"] == "agent_shutdown" for envelope in closed)


async def test_handle_input_and_resize_are_no_ops_for_unknown_session(
    service: TerminalService, sender: FakeSender
) -> None:
    unknown_id = uuid4()

    await service.handle_input(
        Envelope(
            protocol_version=1,
            message_type=MessageType.TERMINAL_INPUT,
            payload=TerminalInputPayload(session_id=unknown_id, data="ls\n").model_dump(
                mode="json"
            ),
        )
    )
    await service.handle_resize(
        Envelope(
            protocol_version=1,
            message_type=MessageType.TERMINAL_RESIZE,
            payload=TerminalResizePayload(session_id=unknown_id, cols=80, rows=24).model_dump(
                mode="json"
            ),
        )
    )

    assert sender.sent == []
