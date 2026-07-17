"""Integration: a command that is never acknowledged, or never results, times out/fails.

Uses its own ``server`` fixture (shadowing ``tests/conftest.py``'s) with much
tighter dispatcher ack/execution timeouts, so these tests run in a fraction
of a second instead of waiting out the suite-wide defaults.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness, default_test_settings, run_server
from tests.utils.waiters import wait_for_command_status


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[ServerHarness]:
    """A server with tight dispatcher ack/execution timeouts, for fast timeout tests."""
    settings = default_test_settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        # A real socket round trip is slower than the in-process duck-typed
        # fake server/tests/test_dispatcher_integration.py uses — these need
        # more headroom than that file's near-zero-latency equivalents to
        # avoid a real ack racing a too-tight timeout.
        DISPATCHER_ACK_TIMEOUT_SECONDS=1.0,
        DISPATCHER_EXECUTION_TIMEOUT_SECONDS=0.5,
        DISPATCHER_MAX_RETRIES=1,
        DISPATCHER_RETRY_BACKOFF_BASE_SECONDS=0.1,
        DISPATCHER_RETRY_BACKOFF_MAX_SECONDS=0.3,
    )
    async with run_server(settings) as harness:
        yield harness


async def test_a_never_acknowledged_command_fails_after_retries(server: ServerHarness) -> None:
    """An agent that never acks exhausts the dispatcher's retry budget and fails."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    agent.respond_to_commands = False
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "system.echo")

    final = await wait_for_command_status(server, command_id, "FAILED", timeout=5.0)
    assert final["retry_count"] >= 1

    await agent.disconnect()


async def test_an_acknowledged_command_with_no_result_times_out(server: ServerHarness) -> None:
    """An agent that acks but never sends a result reaches TIMEOUT, not FAILED."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    agent.handler_delay = 100.0  # effectively "never" within this test's patience
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "system.echo")

    final = await wait_for_command_status(server, command_id, "TIMEOUT", timeout=5.0)
    assert final["completed_at"] is not None

    await agent.disconnect()
