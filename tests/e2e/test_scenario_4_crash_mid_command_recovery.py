"""E2E Scenario 4: agent crashes mid-command -> reconnect -> recovery behavior verified."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness, default_test_settings, run_server
from tests.utils.waiters import wait_for_command_status, wait_for_device_status


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[ServerHarness]:
    """A server with a short execution timeout, so the abandoned command resolves quickly."""
    settings = default_test_settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        DISPATCHER_ACK_TIMEOUT_SECONDS=1.0,
        DISPATCHER_EXECUTION_TIMEOUT_SECONDS=0.3,
    )
    async with run_server(settings) as harness:
        yield harness


async def test_agent_crash_mid_command_then_reconnect_recovers(server: ServerHarness) -> None:
    device_id = await server.register_device(display_name="Scenario 4 Device")
    token = server.issue_device_token(device_id)

    agent = FakeAgent()
    agent.handler_delay = 60.0  # ack, then never get to the result — simulating a crash mid-run
    await agent.connect(server.ws_url, token)
    await wait_for_device_status(server, device_id, "ONLINE")

    command_id = await server.create_command(device_id, "system.echo", payload={"n": 1})

    # The command is acknowledged (RUNNING) before the crash.
    running = await wait_for_command_status(server, command_id, "RUNNING", timeout=3.0)
    assert running["started_at"] is not None

    # Agent crashes mid-command: an abrupt disconnect, no COMMAND_RESULT ever sent.
    await agent.simulate_crash()
    await wait_for_device_status(server, device_id, "OFFLINE")

    # The abandoned command resolves to TIMEOUT rather than hanging RUNNING forever.
    abandoned = await wait_for_command_status(server, command_id, "TIMEOUT", timeout=3.0)
    assert abandoned["completed_at"] is not None

    # Reconnect.
    recovered = FakeAgent()
    await recovered.connect(server.ws_url, token)
    await wait_for_device_status(server, device_id, "ONLINE")

    # Recovery behavior verified: the system is fully usable again — a new
    # command dispatches to the reconnected agent and completes normally.
    new_command_id = await server.create_command(device_id, "system.echo", payload={"n": 2})
    final = await wait_for_command_status(server, new_command_id, "COMPLETED", timeout=3.0)
    assert final["result"]["result"] == {"n": 2}

    await recovered.disconnect()
