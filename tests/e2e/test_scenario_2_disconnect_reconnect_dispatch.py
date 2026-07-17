"""E2E Scenario 2: agent disconnects -> create command -> reconnect -> dispatched -> completes."""

from __future__ import annotations

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import wait_for_command_status, wait_for_device_status


async def test_command_created_offline_dispatches_once_the_agent_reconnects(
    server: ServerHarness,
) -> None:
    device_id = await server.register_device(display_name="Scenario 2 Device")
    token = server.issue_device_token(device_id)

    # Agent connects, then disconnects.
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)
    await wait_for_device_status(server, device_id, "ONLINE")
    await agent.disconnect()
    await wait_for_device_status(server, device_id, "OFFLINE")

    # Create command while nothing is connected.
    command_id = await server.create_command(
        device_id, "system.ping", payload={}, priority="HIGH"
    )
    pending = await server.get_command(command_id)
    assert pending["status"] == "PENDING"

    # Reconnect.
    reconnected = FakeAgent()
    await reconnected.connect(server.ws_url, token)
    await wait_for_device_status(server, device_id, "ONLINE")

    # Command dispatched -> completes.
    final = await wait_for_command_status(server, command_id, "COMPLETED", timeout=5.0)
    assert final["result"]["success"] is True
    assert final["result"]["result"]["status"] == "ok"

    await reconnected.disconnect()
