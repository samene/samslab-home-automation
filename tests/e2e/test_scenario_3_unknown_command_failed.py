"""E2E Scenario 3: unknown command -> agent rejects -> server marks FAILED."""

from __future__ import annotations

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import wait_for_command_status


async def test_unknown_command_is_rejected_by_the_agent_and_marked_failed(
    server: ServerHarness,
) -> None:
    device_id = await server.register_device(display_name="Scenario 3 Device")
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    # A hardware command type no handler exists for yet (Phase 2 ships no
    # GPIO/camera/scheduler handlers) — the agent's own command runtime
    # reports HandlerNotFoundError back as a failed result.
    command_id = await server.create_command(device_id, "gpio.relay_toggle")

    final = await wait_for_command_status(server, command_id, "FAILED")
    assert final["result"]["success"] is False
    assert "Unknown command type" in (final["result"]["error_message"] or "")
    event_types = [event["event_type"] for event in final["events"]]
    assert "COMMAND_FAILED" in event_types

    await agent.disconnect()
