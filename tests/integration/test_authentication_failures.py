"""Integration: every way a WebSocket handshake can fail authentication."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.websocket.constants import CloseCode
from tests.fakes.fake_agent import FakeAgent, FakeAgentError
from tests.utils.failures import MALFORMED_TOKEN, expired_device_token
from tests.utils.server_harness import ServerHarness


async def test_unregistered_device_is_rejected(server: ServerHarness) -> None:
    """A device token for a device that was never registered fails authentication."""
    token = server.issue_device_token(uuid4())
    agent = FakeAgent()

    with pytest.raises(FakeAgentError) as exc_info:
        await agent.connect(server.ws_url, token)

    assert exc_info.value.close_code == CloseCode.AUTHENTICATION_FAILED


async def test_disabled_device_is_rejected(server: ServerHarness) -> None:
    """A device that exists but is disabled fails authentication even with a valid token."""
    device_id = await server.register_device()
    response = await server.http.post(f"/devices/{device_id}/disable")
    response.raise_for_status()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()

    with pytest.raises(FakeAgentError) as exc_info:
        await agent.connect(server.ws_url, token)

    assert exc_info.value.close_code == CloseCode.AUTHENTICATION_FAILED


async def test_expired_token_is_rejected(server: ServerHarness) -> None:
    """A device token that has already expired fails authentication."""
    device_id = await server.register_device()
    token = expired_device_token(server, device_id)
    agent = FakeAgent()

    with pytest.raises(FakeAgentError) as exc_info:
        await agent.connect(server.ws_url, token)

    assert exc_info.value.close_code == CloseCode.AUTHENTICATION_FAILED


async def test_malformed_token_is_rejected(server: ServerHarness) -> None:
    """A syntactically invalid/unsigned token fails authentication rather than crashing the gateway."""
    agent = FakeAgent()

    with pytest.raises(FakeAgentError) as exc_info:
        await agent.connect(server.ws_url, MALFORMED_TOKEN)

    assert exc_info.value.close_code == CloseCode.AUTHENTICATION_FAILED


async def test_a_user_token_cannot_connect_to_the_agent_gateway(server: ServerHarness) -> None:
    """Only device credentials may authenticate this gateway, never a human user token."""
    token = server.issue_user_token()
    agent = FakeAgent()

    with pytest.raises(FakeAgentError) as exc_info:
        await agent.connect(server.ws_url, token)

    assert exc_info.value.close_code == CloseCode.AUTHENTICATION_FAILED
