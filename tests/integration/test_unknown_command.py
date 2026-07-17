"""Integration: a command type the FakeAgent doesn't implement is rejected, not crashed on."""

from __future__ import annotations

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import wait_for_command_status


async def test_unsupported_command_type_is_reported_failed(server: ServerHarness) -> None:
    """A command_type outside the FakeAgent's four supported types fails cleanly.

    Real hardware commands (``gpio.pump_start``, ``camera.capture``, ...) will
    reach exactly this path against today's agent, since Phase 2 implements
    no hardware handlers yet — the agent's own command runtime reports
    ``HandlerNotFoundError`` back as a failed result rather than crashing.
    """
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "gpio.pump_start")

    final = await wait_for_command_status(server, command_id, "FAILED")
    assert final["result"]["success"] is False
    assert "Unknown command type" in (final["result"]["error_message"] or "")

    await agent.disconnect()


async def test_agent_remains_usable_after_an_unknown_command(server: ServerHarness) -> None:
    """A rejected command doesn't wedge the connection — a later valid command still works."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    unknown_id = await server.create_command(device_id, "camera.capture")
    await wait_for_command_status(server, unknown_id, "FAILED")

    echo_id = await server.create_command(device_id, "system.echo", payload={"ok": True})
    final = await wait_for_command_status(server, echo_id, "COMPLETED")
    assert final["result"]["result"] == {"ok": True}

    await agent.disconnect()
