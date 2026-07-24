"""Unit tests for TerminalSessionManager: pure in-memory bookkeeping, no I/O."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.terminal.connection import BrowserConnection
from app.terminal.manager import TerminalSessionManager


def _browser() -> BrowserConnection:
    """A BrowserConnection with no real WebSocket behind it — only used as a set member here."""
    return BrowserConnection(object(), queue_size=10)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_attach_mints_a_new_session_for_a_fresh_device() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()

    session_id, is_new = await manager.attach(device_id, _browser())

    assert is_new is True
    assert manager.session_id_for(device_id) == session_id


@pytest.mark.asyncio
async def test_attach_reuses_the_existing_session_for_a_second_browser() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    first_id, _ = await manager.attach(device_id, _browser())

    second_id, is_new = await manager.attach(device_id, _browser())

    assert is_new is False
    assert second_id == first_id


@pytest.mark.asyncio
async def test_browsers_for_reflects_every_attached_connection() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    first, second = _browser(), _browser()
    await manager.attach(device_id, first)
    await manager.attach(device_id, second)

    assert manager.browsers_for(device_id) == frozenset({first, second})


@pytest.mark.asyncio
async def test_detach_removes_only_the_given_browser() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    first, second = _browser(), _browser()
    await manager.attach(device_id, first)
    await manager.attach(device_id, second)

    await manager.detach(device_id, first)

    assert manager.browsers_for(device_id) == frozenset({second})
    # The session itself is untouched by a browser detaching — only an
    # explicit TERMINAL_CLOSED (mark_closed) ends it.
    assert manager.session_id_for(device_id) is not None


@pytest.mark.asyncio
async def test_detach_is_a_no_op_for_an_unknown_device() -> None:
    manager = TerminalSessionManager()
    await manager.detach(uuid4(), _browser())  # must not raise


@pytest.mark.asyncio
async def test_mark_opened_records_shell_for_the_current_session() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    session_id, _ = await manager.attach(device_id, _browser())

    manager.mark_opened(device_id, session_id, "/bin/bash")

    assert manager.shell_for(device_id) == "/bin/bash"


@pytest.mark.asyncio
async def test_mark_opened_ignores_a_stale_session_id() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    await manager.attach(device_id, _browser())

    manager.mark_opened(device_id, uuid4(), "/bin/bash")

    assert manager.shell_for(device_id) is None


@pytest.mark.asyncio
async def test_mark_closed_resets_session_state_so_a_fresh_one_is_minted_next() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    session_id, _ = await manager.attach(device_id, _browser())
    manager.mark_opened(device_id, session_id, "/bin/bash")

    manager.mark_closed(device_id, session_id)

    assert manager.session_id_for(device_id) is None
    assert manager.shell_for(device_id) is None
    new_id, is_new = await manager.attach(device_id, _browser())
    assert is_new is True
    assert new_id != session_id


@pytest.mark.asyncio
async def test_mark_closed_ignores_a_stale_session_id() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    session_id, _ = await manager.attach(device_id, _browser())

    manager.mark_closed(device_id, uuid4())

    assert manager.session_id_for(device_id) == session_id


def test_session_id_for_and_shell_for_are_none_for_unknown_device() -> None:
    manager = TerminalSessionManager()
    assert manager.session_id_for(uuid4()) is None
    assert manager.shell_for(uuid4()) is None
    assert manager.browsers_for(uuid4()) == frozenset()


@pytest.mark.asyncio
async def test_force_clear_removes_a_tracked_session_and_returns_its_browsers() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    first, second = _browser(), _browser()
    session_id, _ = await manager.attach(device_id, first)
    await manager.attach(device_id, second)
    manager.mark_opened(device_id, session_id, "/bin/bash")

    cleared = manager.force_clear(device_id)

    assert cleared == (session_id, frozenset({first, second}))
    assert manager.session_id_for(device_id) is None
    assert manager.shell_for(device_id) is None


def test_force_clear_is_a_no_op_for_a_device_with_no_tracked_session() -> None:
    manager = TerminalSessionManager()
    assert manager.force_clear(uuid4()) is None


@pytest.mark.asyncio
async def test_force_clear_lets_a_subsequent_attach_mint_a_fresh_session() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    old_session_id, _ = await manager.attach(device_id, _browser())

    manager.force_clear(device_id)
    new_session_id, is_new = await manager.attach(device_id, _browser())

    assert is_new is True
    assert new_session_id != old_session_id


@pytest.mark.asyncio
async def test_append_output_accumulates_and_output_buffer_for_returns_it() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    await manager.attach(device_id, _browser())

    manager.append_output(device_id, "hello ")
    manager.append_output(device_id, "world\n")

    assert manager.output_buffer_for(device_id) == "hello world\n"


def test_append_output_is_a_no_op_for_an_unknown_device() -> None:
    manager = TerminalSessionManager()
    manager.append_output(uuid4(), "data")  # must not raise


def test_output_buffer_for_is_empty_for_an_unknown_device() -> None:
    manager = TerminalSessionManager()
    assert manager.output_buffer_for(uuid4()) == ""


@pytest.mark.asyncio
async def test_append_output_is_bounded_and_keeps_only_the_tail() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    await manager.attach(device_id, _browser())

    manager.append_output(device_id, "a" * 20000)
    manager.append_output(device_id, "b" * 100)

    buffer = manager.output_buffer_for(device_id)
    assert len(buffer) == 16384
    assert buffer.endswith("b" * 100)


@pytest.mark.asyncio
async def test_a_fresh_session_after_mark_closed_does_not_replay_the_old_buffer() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    session_id, _ = await manager.attach(device_id, _browser())
    manager.append_output(device_id, "old session output")
    manager.mark_closed(device_id, session_id)

    await manager.attach(device_id, _browser())

    assert manager.output_buffer_for(device_id) == ""


@pytest.mark.asyncio
async def test_a_fresh_session_after_force_clear_does_not_replay_the_old_buffer() -> None:
    manager = TerminalSessionManager()
    device_id = uuid4()
    await manager.attach(device_id, _browser())
    manager.append_output(device_id, "old session output")
    manager.force_clear(device_id)

    await manager.attach(device_id, _browser())

    assert manager.output_buffer_for(device_id) == ""
