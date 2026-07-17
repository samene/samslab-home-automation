"""Integration: agent-initiated heartbeat over a real WebSocket.

A connected ``FakeAgent`` already runs its own background receive loop (it
auto-replies PONG to a server PING, and records everything it receives), so
these tests observe behavior through ``agent.received``/REST polling rather
than racing that loop with a second, manual ``recv()``.
"""

from __future__ import annotations

from shared.protocol.message_types import MessageType
from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import (
    wait_for_device_status,
    wait_for_message,
    wait_for_session,
    wait_until,
)


async def test_agent_initiated_heartbeat_gets_a_pong(server: ServerHarness) -> None:
    """An agent sending PING receives PONG and the device is reported ONLINE."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    await wait_for_device_status(server, device_id, "ONLINE")

    await agent.send_heartbeat()
    await wait_for_message(agent, MessageType.PONG)

    await agent.disconnect()


async def test_disconnect_marks_the_device_offline(server: ServerHarness) -> None:
    """A graceful GOODBYE disconnect updates the device's status to OFFLINE."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)
    await wait_for_device_status(server, device_id, "ONLINE")

    await agent.disconnect()

    await wait_for_device_status(server, device_id, "OFFLINE")


async def test_periodic_heartbeat_keeps_the_session_last_seen_advancing(
    server: ServerHarness,
) -> None:
    """The live session's last_seen (not the device's DB row) advances with every heartbeat.

    Only connect/disconnect update the device's own persisted ``last_seen``;
    per-message liveness lives on the in-memory session the heartbeat monitor
    watches (``app/websocket/heartbeat.py``) — exposed via ``GET /ws/sessions/{id}``.
    """
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)
    admin_token = server.issue_user_token()

    first_session = await wait_for_session(server, admin_token, device_id)
    agent.start_heartbeat(interval=0.05)

    async def _session_advanced() -> bool:
        current = await server.session_for(admin_token, device_id)
        return bool(current and current["last_seen"] != first_session["last_seen"])

    await wait_until(_session_advanced, timeout=3.0, description="session last_seen to advance")

    await agent.disconnect()
