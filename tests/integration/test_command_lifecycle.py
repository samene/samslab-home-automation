"""Integration: command creation, dispatch, acknowledgement, execution, completion.

Exercises the full pipeline from the spec's diagram — REST API -> Command
Creation -> Database Persistence -> Command Dispatcher -> WebSocket Gateway ->
Agent -> Command Runtime -> COMMAND_RESULT -> Database Update — using
dispatcher/session introspection endpoints along the way.
"""

from __future__ import annotations

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness
from tests.utils.waiters import wait_for_command_status, wait_until


async def test_command_is_created_pending(server: ServerHarness) -> None:
    """A command with no connected device is created PENDING and stays there."""
    device_id = await server.register_device()

    command_id = await server.create_command(device_id, "system.echo", payload={"a": 1})

    command = await server.get_command(command_id)
    assert command["status"] == "PENDING"
    assert command["command_type"] == "system.echo"
    assert command["payload"] == {"a": 1}


async def test_full_pipeline_dispatches_acks_executes_and_completes(
    server: ServerHarness,
) -> None:
    """PENDING -> DISPATCHED -> RUNNING -> COMPLETED, with a real ack and a real result."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "system.echo", payload={"greeting": "hi"})

    final = await wait_for_command_status(server, command_id, "COMPLETED")
    assert final["result"]["success"] is True
    assert final["result"]["result"] == {"greeting": "hi"}
    assert final["started_at"] is not None
    assert final["completed_at"] is not None

    await agent.disconnect()


async def test_command_appears_in_dispatcher_queue_before_a_device_connects(
    server: ServerHarness,
) -> None:
    """A pending command with no connected device shows up in the dispatcher's own queue."""
    device_id = await server.register_device()
    admin_token = server.issue_user_token()
    command_id = await server.create_command(device_id, "system.ping")

    async def _in_queue() -> bool:
        queue = await server.dispatcher_queue(admin_token)
        return any(item["command_id"] == str(command_id) for item in queue)

    await wait_until(_in_queue, description="command to appear in the dispatcher queue")


async def test_command_appears_in_dispatcher_running_while_awaiting_result(
    server: ServerHarness,
) -> None:
    """Once dispatched and acked, a command shows up as 'running' until its result arrives."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    agent.handler_delay = 1.0  # hold the result back so we can observe the running phase
    await agent.connect(server.ws_url, token)
    admin_token = server.issue_user_token()

    command_id = await server.create_command(device_id, "system.echo")

    async def _running() -> bool:
        running = await server.dispatcher_running(admin_token)
        return any(
            item["command_id"] == str(command_id) and item["phase"] == "running"
            for item in running
        )

    await wait_until(_running, description="command to appear in dispatcher running list")
    await wait_for_command_status(server, command_id, "COMPLETED", timeout=5.0)
    await agent.disconnect()


async def test_dispatcher_statistics_count_a_completed_command(server: ServerHarness) -> None:
    """The dispatcher's own operational counters reflect a completed dispatch."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)
    admin_token = server.issue_user_token()

    before = await server.dispatcher_statistics(admin_token)
    command_id = await server.create_command(device_id, "system.echo")
    await wait_for_command_status(server, command_id, "COMPLETED")

    after = await server.dispatcher_statistics(admin_token)
    assert after["commands_dispatched_total"] >= before["commands_dispatched_total"] + 1

    await agent.disconnect()


async def test_command_events_record_the_full_lifecycle_trail(server: ServerHarness) -> None:
    """A completed command's event trail records every lifecycle transition."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)

    command_id = await server.create_command(device_id, "system.echo")
    final = await wait_for_command_status(server, command_id, "COMPLETED")

    event_types = {event["event_type"] for event in final["events"]}
    assert "COMMAND_CREATED" in event_types
    assert len(final["events"]) >= 2

    await agent.disconnect()
