"""Integration: a result that arrives after a command is already terminal is dropped."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness, default_test_settings, run_server
from tests.utils.waiters import wait_for_command_status, wait_until


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[ServerHarness]:
    """A server with a tight execution timeout, so a delayed result reliably arrives late."""
    settings = default_test_settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        DISPATCHER_ACK_TIMEOUT_SECONDS=1.0,
        DISPATCHER_EXECUTION_TIMEOUT_SECONDS=0.3,
        DISPATCHER_MAX_RETRIES=0,
    )
    async with run_server(settings) as harness:
        yield harness


async def test_a_result_after_timeout_does_not_resurrect_the_command(
    server: ServerHarness,
) -> None:
    """A result that finally arrives after TIMEOUT is logged and dropped, not reapplied."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    agent.handler_delay = 0.6  # longer than the 0.3s execution timeout above
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "system.echo")

    timed_out = await wait_for_command_status(server, command_id, "TIMEOUT", timeout=3.0)
    timed_out_completed_at = timed_out["completed_at"]

    # The agent's delayed result eventually arrives (0.6s after ack) — well
    # after the server already gave up. Give it time to arrive and settle.
    async def _still_timeout() -> bool:
        current = await server.get_command(command_id)
        return bool(
            current["status"] == "TIMEOUT" and current["completed_at"] == timed_out_completed_at
        )

    await wait_until(
        _still_timeout, timeout=2.0, description="the late result to be dropped, not reapplied"
    )

    await agent.disconnect()


async def test_duplicate_results_are_only_applied_once(server: ServerHarness) -> None:
    """A duplicated result frame for an already-completed command changes nothing further."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    agent.duplicate_next_result = True
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "system.echo")
    final = await wait_for_command_status(server, command_id, "COMPLETED")

    async def _still_completed() -> bool:
        current = await server.get_command(command_id)
        return bool(
            current["status"] == "COMPLETED"
            and current["completed_at"] == final["completed_at"]
        )

    await wait_until(_still_completed, timeout=1.0, description="the duplicate result to be dropped")

    await agent.disconnect()
