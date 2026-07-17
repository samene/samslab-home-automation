"""Integration: a device cannot hold two open sessions at once."""

from __future__ import annotations

from app.websocket.constants import CloseCode
from tests.fakes.fake_agent import FakeAgent, FakeAgentError
from tests.utils.server_harness import ServerHarness


async def test_second_connection_for_the_same_device_is_rejected(server: ServerHarness) -> None:
    """A second concurrent connection for an already-connected device is closed immediately."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)

    first = FakeAgent()
    await first.connect(server.ws_url, token)

    second = FakeAgent()
    try:
        await second.connect(server.ws_url, token)
        raised = False
    except FakeAgentError as error:
        raised = True
        assert error.close_code == CloseCode.DUPLICATE_SESSION

    assert raised, "a second connection for the same device must be rejected"

    await first.disconnect()


async def test_after_the_first_disconnects_a_second_connection_succeeds(
    server: ServerHarness,
) -> None:
    """Once the first session ends, a new connection for the same device is accepted."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)

    first = FakeAgent()
    await first.connect(server.ws_url, token)
    await first.disconnect()

    second = FakeAgent()
    welcome = await second.connect(server.ws_url, token)
    assert welcome.session_id is not None

    await second.disconnect()
