"""Tests for register_terminal_relay: event bus -> attached browsers broadcast."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    DeviceHeartbeat,
    TerminalClosedReceived,
    TerminalErrorReceived,
    TerminalOpenedReceived,
    TerminalOutputReceived,
)
from app.terminal.connection import BrowserConnection
from app.terminal.manager import TerminalSessionManager
from app.terminal.relay import register_terminal_relay
from app.websocket.protocol import MessageType
from app.websocket.schemas import Envelope


def _browser() -> BrowserConnection:
    return BrowserConnection(object(), queue_size=10)  # type: ignore[arg-type]


async def _drain(browser: BrowserConnection) -> dict[str, Any]:
    envelope = browser._queue.get_nowait()  # noqa: SLF001 - reaching into private state to assert
    return json.loads(envelope.model_dump_json())  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_terminal_output_is_broadcast_to_every_attached_browser() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    first, second = _browser(), _browser()
    session_id, _ = await manager.attach(device_id, first)
    await manager.attach(device_id, second)

    await event_bus.publish(
        TerminalOutputReceived(
            device_id=device_id, session_id=session_id, data="hello", occurred_at=datetime.now(UTC)
        )
    )

    for browser in (first, second):
        payload = await _drain(browser)
        assert payload["message_type"] == "TERMINAL_OUTPUT"
        assert payload["payload"]["data"] == "hello"
    assert manager.output_buffer_for(device_id) == "hello"


@pytest.mark.asyncio
async def test_terminal_opened_updates_the_manager_and_broadcasts() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    browser = _browser()
    session_id, _ = await manager.attach(device_id, browser)

    await event_bus.publish(
        TerminalOpenedReceived(
            device_id=device_id,
            session_id=session_id,
            shell="/bin/bash",
            occurred_at=datetime.now(UTC),
        )
    )

    assert manager.shell_for(device_id) == "/bin/bash"
    payload = await _drain(browser)
    assert payload["message_type"] == "TERMINAL_OPENED"
    assert payload["payload"]["shell"] == "/bin/bash"


@pytest.mark.asyncio
async def test_terminal_closed_clears_the_manager_and_broadcasts() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    browser = _browser()
    session_id, _ = await manager.attach(device_id, browser)
    manager.mark_opened(device_id, session_id, "/bin/bash")

    await event_bus.publish(
        TerminalClosedReceived(
            device_id=device_id,
            session_id=session_id,
            reason="shell_exited",
            exit_code=0,
            occurred_at=datetime.now(UTC),
        )
    )

    assert manager.session_id_for(device_id) is None
    payload = await _drain(browser)
    assert payload["message_type"] == "TERMINAL_CLOSED"
    assert payload["payload"]["reason"] == "shell_exited"
    assert payload["payload"]["exit_code"] == 0


@pytest.mark.asyncio
async def test_terminal_error_is_broadcast_without_touching_manager_state() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    browser = _browser()
    session_id, _ = await manager.attach(device_id, browser)

    await event_bus.publish(
        TerminalErrorReceived(
            device_id=device_id,
            session_id=session_id,
            code="spawn_failed",
            message="Failed to start a shell on this device",
            occurred_at=datetime.now(UTC),
        )
    )

    assert manager.session_id_for(device_id) == session_id
    payload = await _drain(browser)
    assert payload["message_type"] == "TERMINAL_ERROR"
    assert payload["payload"]["code"] == "spawn_failed"


@pytest.mark.asyncio
async def test_broadcast_to_a_device_with_no_attached_browsers_does_not_raise() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)

    await event_bus.publish(
        TerminalOutputReceived(
            device_id=uuid4(), session_id=uuid4(), data="x", occurred_at=datetime.now(UTC)
        )
    )  # must not raise


@pytest.mark.asyncio
async def test_a_full_browser_queue_does_not_block_broadcasting_to_others() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    full_browser = BrowserConnection(object(), queue_size=1)  # type: ignore[arg-type]
    healthy_browser = _browser()
    session_id, _ = await manager.attach(device_id, full_browser)
    await manager.attach(device_id, healthy_browser)
    filler = Envelope(protocol_version=1, message_type=MessageType.PING, payload={})
    full_browser._queue.put_nowait(filler)  # noqa: SLF001 - fill capacity to force backpressure

    await event_bus.publish(
        TerminalOutputReceived(
            device_id=device_id, session_id=session_id, data="x", occurred_at=datetime.now(UTC)
        )
    )

    payload = await _drain(healthy_browser)
    assert payload["message_type"] == "TERMINAL_OUTPUT"


@pytest.mark.asyncio
async def test_device_offline_force_clears_the_session_and_notifies_attached_browsers() -> None:
    """The gateway publishes DeviceHeartbeat(status=OFFLINE) on every agent
    disconnect, clean or not — this is the backstop for a crash/network-loss
    that never sends its own TERMINAL_CLOSED (see docs/agent/TERMINAL.md)."""
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    browser = _browser()
    session_id, _ = await manager.attach(device_id, browser)
    manager.mark_opened(device_id, session_id, "/bin/bash")

    await event_bus.publish(
        DeviceHeartbeat(device_id=device_id, status="OFFLINE", occurred_at=datetime.now(UTC))
    )

    assert manager.session_id_for(device_id) is None
    payload = await _drain(browser)
    assert payload["message_type"] == "TERMINAL_CLOSED"
    assert payload["payload"]["session_id"] == str(session_id)
    assert payload["payload"]["reason"] == "agent_disconnected"


@pytest.mark.asyncio
async def test_device_online_heartbeat_does_not_touch_a_tracked_session() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)
    device_id = uuid4()
    session_id, _ = await manager.attach(device_id, _browser())

    await event_bus.publish(
        DeviceHeartbeat(device_id=device_id, status="ONLINE", occurred_at=datetime.now(UTC))
    )

    assert manager.session_id_for(device_id) == session_id


@pytest.mark.asyncio
async def test_device_offline_with_no_tracked_session_does_not_raise() -> None:
    event_bus = EventBus()
    manager = TerminalSessionManager()
    register_terminal_relay(event_bus, manager)

    await event_bus.publish(
        DeviceHeartbeat(device_id=uuid4(), status="OFFLINE", occurred_at=datetime.now(UTC))
    )  # must not raise
