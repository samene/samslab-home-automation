"""Reusable device/agent setup helpers combining a ``ServerHarness`` with a ``FakeAgent``."""

from __future__ import annotations

from uuid import UUID

from tests.fakes.fake_agent import FakeAgent
from tests.utils.server_harness import ServerHarness


async def register_and_connect(
    server: ServerHarness,
    *,
    device_name: str | None = None,
    heartbeat_interval: float | None = None,
) -> tuple[UUID, FakeAgent]:
    """Register a device through the real REST API, then connect+authenticate a FakeAgent for it."""
    device_id = await server.register_device(device_name=device_name)
    token = server.issue_device_token(device_id)
    agent = FakeAgent()
    await agent.connect(server.ws_url, token)
    if heartbeat_interval is not None:
        agent.start_heartbeat(heartbeat_interval)
    return device_id, agent
