"""Tests for the default WebSocket connector."""

from __future__ import annotations

from typing import Any

import pytest
import websockets

from app.connection.transport import connect_websocket


@pytest.mark.asyncio
async def test_connect_websocket_delegates_to_websockets_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connect_websocket awaits websockets.connect and returns its result."""
    sentinel = object()

    async def fake_connect(url: str) -> Any:
        assert url == "ws://example/ws"
        return sentinel

    monkeypatch.setattr(websockets, "connect", fake_connect)

    result = await connect_websocket("ws://example/ws")

    assert result is sentinel
