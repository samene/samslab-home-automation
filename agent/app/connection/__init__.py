"""The agent's outbound WebSocket connection: connect, authenticate, heartbeat, reconnect."""

from app.connection.backoff import ExponentialBackoff
from app.connection.exceptions import (
    AuthenticationRejectedError,
    ConnectionManagerError,
    DeviceTokenRequestError,
    NotConnectedError,
)
from app.connection.manager import ConnectionManager
from app.connection.token_provider import fetch_device_token
from app.connection.transport import WebSocketConnection, WebSocketConnector, connect_websocket

__all__ = [
    "AuthenticationRejectedError",
    "ConnectionManager",
    "ConnectionManagerError",
    "DeviceTokenRequestError",
    "ExponentialBackoff",
    "NotConnectedError",
    "WebSocketConnection",
    "WebSocketConnector",
    "connect_websocket",
    "fetch_device_token",
]
