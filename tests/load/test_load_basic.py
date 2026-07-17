"""A lightweight load test: many concurrent agents, many concurrent commands.

Not a substitute for a dedicated load-testing tool — this exists to catch
concurrency bugs (races in the dispatcher, session manager, or command
runtime) under modest parallel load, using the same real-protocol FakeAgent
as every other test in this framework. Marked ``load`` so it can be run in
isolation (``pytest -m load``) or excluded (``pytest -m "not load"``); by
default it still runs as part of the whole suite.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import wait_for_command_status

pytestmark = pytest.mark.load

AGENT_COUNT = 10
COMMANDS_PER_AGENT = 5


async def _run_agent_workload(server: ServerHarness, index: int) -> list[dict[str, object]]:
    """Register one device, connect one agent, run its commands to completion."""
    device_id = await server.register_device(device_name=f"load-agent-{index}")
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    command_ids = [
        await server.create_command(device_id, "system.echo", payload={"i": i})
        for i in range(COMMANDS_PER_AGENT)
    ]
    # A generous timeout: under heavy contention (e.g. the whole test suite
    # running concurrently with other real-socket-heavy tests), real asyncio
    # scheduling can occasionally slow dispatch well below its typical speed.
    results = [
        await wait_for_command_status(server, command_id, "COMPLETED", timeout=30.0)
        for command_id in command_ids
    ]

    await agent.disconnect()
    return results


async def test_many_agents_many_commands_all_complete(server: ServerHarness) -> None:
    """AGENT_COUNT agents each running COMMANDS_PER_AGENT commands, all concurrently."""
    started = time.monotonic()

    all_results = await asyncio.gather(
        *(_run_agent_workload(server, i) for i in range(AGENT_COUNT))
    )

    duration = time.monotonic() - started
    total_commands = AGENT_COUNT * COMMANDS_PER_AGENT
    completed = sum(
        1 for results in all_results for result in results if result["status"] == "COMPLETED"
    )

    assert completed == total_commands
    print(f"\n{total_commands} commands across {AGENT_COUNT} agents completed in {duration:.2f}s")


async def test_dispatcher_statistics_reflect_the_full_batch(server: ServerHarness) -> None:
    """The dispatcher's own operational counters account for every dispatched command."""
    admin_token = server.issue_user_token()
    before = await server.dispatcher_statistics(admin_token)

    await asyncio.gather(*(_run_agent_workload(server, i) for i in range(AGENT_COUNT)))

    after = await server.dispatcher_statistics(admin_token)
    total_commands = AGENT_COUNT * COMMANDS_PER_AGENT
    assert after["commands_dispatched_total"] >= before["commands_dispatched_total"] + total_commands
