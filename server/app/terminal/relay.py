"""Subscribes to agent-originated terminal events on the shared event bus and
forwards them to every browser connection currently attached to that device.

Registered once per application (see ``app/core/container.py``'s
``build_container``, mirroring ``register_logging_subscriber``/
``register_notification_subscribers``) — not per-connection, so N attached
browser tabs for the same device all see identical output from one shared
subscription rather than N independent ones.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import UUID

import structlog

from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    DeviceHeartbeat,
    TerminalClosedReceived,
    TerminalErrorReceived,
    TerminalOpenedReceived,
    TerminalOutputReceived,
)
from app.domains.devices.models import DeviceStatus
from app.terminal.connection import BackpressureExceededError
from app.terminal.manager import TerminalSessionManager
from app.websocket.protocol import PROTOCOL_VERSION, MessageType
from app.websocket.schemas import (
    Envelope,
    TerminalClosedPayload,
    TerminalErrorPayload,
    TerminalOpenedPayload,
    TerminalOutputPayload,
)

logger: Any = structlog.get_logger("terminal.relay")


def register_terminal_relay(
    event_bus: EventBus, terminal_session_manager: TerminalSessionManager
) -> None:
    """Wire every ``Terminal*Received`` event to a broadcast onto attached browsers."""

    async def on_opened(event: TerminalOpenedReceived) -> None:
        terminal_session_manager.mark_opened(event.device_id, event.session_id, event.shell)
        _broadcast(
            terminal_session_manager,
            event.device_id,
            Envelope(
                protocol_version=PROTOCOL_VERSION,
                message_type=MessageType.TERMINAL_OPENED,
                payload=TerminalOpenedPayload(
                    session_id=event.session_id, shell=event.shell
                ).model_dump(mode="json"),
            ),
        )

    async def on_output(event: TerminalOutputReceived) -> None:
        terminal_session_manager.append_output(event.device_id, event.data)
        _broadcast(
            terminal_session_manager,
            event.device_id,
            Envelope(
                protocol_version=PROTOCOL_VERSION,
                message_type=MessageType.TERMINAL_OUTPUT,
                payload=TerminalOutputPayload(
                    session_id=event.session_id, data=event.data
                ).model_dump(mode="json"),
            ),
        )

    async def on_closed(event: TerminalClosedReceived) -> None:
        terminal_session_manager.mark_closed(event.device_id, event.session_id)
        _broadcast(
            terminal_session_manager,
            event.device_id,
            Envelope(
                protocol_version=PROTOCOL_VERSION,
                message_type=MessageType.TERMINAL_CLOSED,
                payload=TerminalClosedPayload(
                    session_id=event.session_id, reason=event.reason, exit_code=event.exit_code
                ).model_dump(mode="json"),
            ),
        )

    async def on_error(event: TerminalErrorReceived) -> None:
        _broadcast(
            terminal_session_manager,
            event.device_id,
            Envelope(
                protocol_version=PROTOCOL_VERSION,
                message_type=MessageType.TERMINAL_ERROR,
                payload=TerminalErrorPayload(
                    session_id=event.session_id, code=event.code, message=event.message
                ).model_dump(mode="json"),
            ),
        )

    async def on_device_offline(event: DeviceHeartbeat) -> None:
        # The WebSocket Gateway publishes this unconditionally on every
        # disconnect — clean or not — from its own `finally` block
        # (`_mark_offline_best_effort`), which is what makes it a reliable
        # signal here even when the agent never got to (or never tried to)
        # send its own TERMINAL_CLOSED: a crash, a lost network path, or a
        # graceful shutdown that lost the race against its own disconnect
        # (see docs/agent/TERMINAL.md) all look identical from here — the
        # agent's connection is gone, so no tracked PTY session can possibly
        # still be alive, regardless of what it last told us.
        if event.status != DeviceStatus.OFFLINE.value:
            return
        cleared = terminal_session_manager.force_clear(event.device_id)
        if cleared is None:
            return
        session_id, browsers = cleared
        logger.info(
            "terminal_force_cleared_on_agent_disconnect",
            device_id=str(event.device_id),
            session_id=str(session_id),
        )
        envelope = Envelope(
            protocol_version=PROTOCOL_VERSION,
            message_type=MessageType.TERMINAL_CLOSED,
            payload=TerminalClosedPayload(
                session_id=session_id, reason="agent_disconnected", exit_code=None
            ).model_dump(mode="json"),
        )
        for browser in browsers:
            with contextlib.suppress(BackpressureExceededError):
                browser.enqueue(envelope)

    event_bus.subscribe(TerminalOpenedReceived, on_opened)
    event_bus.subscribe(TerminalOutputReceived, on_output)
    event_bus.subscribe(TerminalClosedReceived, on_closed)
    event_bus.subscribe(TerminalErrorReceived, on_error)
    event_bus.subscribe(DeviceHeartbeat, on_device_offline)


def _broadcast(manager: TerminalSessionManager, device_id: UUID, envelope: Envelope) -> None:
    for browser in manager.browsers_for(device_id):
        with contextlib.suppress(BackpressureExceededError):
            browser.enqueue(envelope)
