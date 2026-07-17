"""Integration: disconnect and reconnect behavior."""

from __future__ import annotations

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import (
    wait_for_command_status,
    wait_for_device_status,
    wait_for_no_session,
    wait_for_session,
)


async def test_reconnect_after_graceful_disconnect_creates_a_new_session(
    server: ServerHarness,
) -> None:
    """After a GOODBYE disconnect, the same device can reconnect and gets a new session."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    admin_token = server.issue_user_token()

    first_agent = FakeAgent()
    await first_agent.connect(server.ws_url, token)
    first_session = await wait_for_session(server, admin_token, device_id)

    await first_agent.disconnect()
    await wait_for_no_session(server, admin_token, device_id)
    await wait_for_device_status(server, device_id, "OFFLINE")

    second_agent = FakeAgent()
    await second_agent.connect(server.ws_url, token)
    second_session = await wait_for_session(server, admin_token, device_id)

    assert second_session["connection_id"] != first_session["connection_id"]
    await wait_for_device_status(server, device_id, "ONLINE")

    await second_agent.disconnect()


async def test_reconnect_after_abrupt_crash_is_accepted(server: ServerHarness) -> None:
    """After an abrupt disconnect (no GOODBYE), the device can still reconnect."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    admin_token = server.issue_user_token()

    agent = FakeAgent()
    await agent.connect(server.ws_url, token)
    await wait_for_session(server, admin_token, device_id)

    await agent.simulate_crash()
    await wait_for_no_session(server, admin_token, device_id)

    reconnected = FakeAgent()
    await reconnected.connect(server.ws_url, token)
    await wait_for_session(server, admin_token, device_id)

    await reconnected.disconnect()


async def test_command_created_while_disconnected_dispatches_after_reconnect(
    server: ServerHarness,
) -> None:
    """A command created while offline stays PENDING, then dispatches once the agent reconnects."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)

    command_id = await server.create_command(device_id, "system.echo", payload={"n": 1})
    pending = await server.get_command(command_id)
    assert pending["status"] == "PENDING"

    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    final = await wait_for_command_status(server, command_id, "COMPLETED")
    assert final["result"]["result"] == {"n": 1}

    await agent.disconnect()
