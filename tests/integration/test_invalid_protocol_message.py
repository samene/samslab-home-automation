"""Integration: malformed or out-of-order messages are protocol violations, not crashes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import websockets

from app.websocket.constants import CloseCode
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope, PingPayload
from tests.fakes.fake_agent import FakeAgent, FakeAgentError
from tests.utils.server_harness import ServerHarness, default_test_settings, run_server


async def test_first_message_must_be_hello(server: ServerHarness) -> None:
    """Sending anything other than HELLO first is a protocol violation."""
    agent = FakeAgent()
    await agent.connect_raw(server.ws_url)
    await agent.send_envelope(
        Envelope(
            protocol_version=1,
            message_type=MessageType.PING,
            payload=PingPayload().model_dump(mode="json"),
        )
    )

    with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
        await agent.recv_envelope()

    assert exc_info.value.rcvd is not None
    assert exc_info.value.rcvd.code == CloseCode.PROTOCOL_VIOLATION


async def test_malformed_hello_payload_is_a_protocol_violation(server: ServerHarness) -> None:
    """A HELLO payload missing its required token field fails schema validation."""
    agent = FakeAgent()
    await agent.connect_raw(server.ws_url)
    await agent.send_raw_text(
        json.dumps(
            {
                "protocol_version": 1,
                "message_type": "HELLO",
                "payload": {"agent_version": "1.0.0"},
            }
        )
    )

    with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
        await agent.recv_envelope()

    assert exc_info.value.rcvd is not None
    assert exc_info.value.rcvd.code == CloseCode.PROTOCOL_VIOLATION


async def test_malformed_json_is_a_protocol_violation(server: ServerHarness) -> None:
    """Raw text that isn't even valid JSON is a protocol violation, not a crash."""
    agent = FakeAgent()
    await agent.connect_raw(server.ws_url)
    await agent.send_raw_text("this is not json at all {{{")

    with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
        await agent.recv_envelope()

    assert exc_info.value.rcvd is not None
    assert exc_info.value.rcvd.code == CloseCode.PROTOCOL_VIOLATION


async def test_unsupported_protocol_version_is_rejected(server: ServerHarness) -> None:
    """A HELLO requesting an unsupported protocol version fails negotiation."""
    device_id = await server.register_device()
    token = server.issue_device_token(device_id)
    agent = FakeAgent()

    with pytest.raises(FakeAgentError) as exc_info:
        await agent.connect(server.ws_url, token, protocol_version=999)

    assert exc_info.value.close_code == CloseCode.UNSUPPORTED_PROTOCOL_VERSION


@pytest.fixture
async def fast_hello_timeout_server(tmp_path: Path) -> AsyncIterator[ServerHarness]:
    """A server with a very short HELLO handshake window, so the timeout test runs quickly."""
    settings = default_test_settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}",
        WS_HELLO_TIMEOUT_SECONDS=0.2,
    )
    async with run_server(settings) as harness:
        yield harness


async def test_handshake_timeout_closes_a_silent_connection(
    fast_hello_timeout_server: ServerHarness,
) -> None:
    """A connection that never sends HELLO is closed once the handshake window elapses."""
    agent = FakeAgent()
    await agent.connect_raw(fast_hello_timeout_server.ws_url)

    with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
        await agent.recv_envelope(timeout=2.0)

    assert exc_info.value.rcvd is not None
    assert exc_info.value.rcvd.code == CloseCode.HANDSHAKE_TIMEOUT
