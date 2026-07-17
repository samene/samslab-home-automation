"""The WebSocket transport seam the connection manager depends on.

``WebSocketConnection`` is a structural (``Protocol``) type rather than a
concrete class so the connection manager can be dependency-injected with a
fake in tests without importing the real ``websockets`` library at all.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import websockets


class WebSocketConnection(Protocol):
    """The subset of a WebSocket client connection the agent relies on."""

    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self, *, code: int = 1000, reason: str = "") -> None: ...


#: A connector opens a new transport to ``server_url`` and returns it once open.
WebSocketConnector = Callable[[str], Awaitable[WebSocketConnection]]


async def connect_websocket(server_url: str) -> WebSocketConnection:
    """The production connector: a real outbound ``websockets`` client connection."""
    return await websockets.connect(server_url)
