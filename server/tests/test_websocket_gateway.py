"""Integration tests for the full WebSocket connection lifecycle via TestClient.

Device fixtures are always registered through a self-contained ``anyio.run()``
call that starts and fully closes its own event loop *before* ``TestClient``
opens its own portal thread and loop. Doing it any other way — e.g. calling
``anyio.run()`` while a ``TestClient`` context is already open — races two
live event loops against the same SQLAlchemy async engine and reliably hangs.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.tokens import new_jti
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.main import create_app
from app.websocket.constants import CloseCode

_JWT_SECRET = "a-sufficiently-long-test-signing-secret-value"


@pytest.fixture
def settings(tmp_path: object) -> Settings:
    """Deterministic, fast-timing settings so lifecycle tests run quickly."""
    return Settings(
        SERVER_NAME="WS Test Server",
        ENVIRONMENT=Environment.TEST,
        JWT_SECRET=_JWT_SECRET,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path}/ws.db",
        WS_HEARTBEAT_INTERVAL_SECONDS=30.0,
        WS_HEARTBEAT_TIMEOUT_SECONDS=10.0,
        WS_IDLE_TIMEOUT_SECONDS=90.0,
        WS_HELLO_TIMEOUT_SECONDS=0.3,
        WS_OUTGOING_QUEUE_SIZE=10,
        WS_MESSAGE_ACK_TIMEOUT_SECONDS=5.0,
        WS_MESSAGE_ACK_MAX_RETRIES=2,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Create a fresh application instance with its schema already created.

    Schema creation happens here — via a self-contained event loop, before any
    ``TestClient`` opens its own portal thread — so every test has working
    tables even if it never registers a device of its own.
    """
    application = create_app(settings)

    async def _create_schema() -> None:
        database: Database = application.state.container.database()
        await database.create_schema_for_testing()

    anyio.run(_create_schema)
    return application


@pytest.fixture
def jwt_codec(settings: Settings) -> JWTCodec:
    """Build the same JWT codec the gateway itself builds from settings."""
    return JWTCodec(
        secret=settings.jwt_secret.get_secret_value(),  # type: ignore[union-attr]
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        clock_skew_seconds=settings.jwt_clock_skew_seconds,
    )


def _device_token(
    jwt_codec: JWTCodec, device_id: UUID, *, expires_in: timedelta | None = None
) -> str:
    return jwt_codec.encode(
        subject=str(device_id),
        expires_in=expires_in or timedelta(minutes=5),
        jti=new_jti(),
        claims={
            "principal_type": "DEVICE",
            "role": ["Agent"],
            "permissions": sorted(permissions_for_roles(["Agent"])),
            "device_id": str(device_id),
        },
    )


def _user_token(jwt_codec: JWTCodec, *, roles: list[str] | None = None) -> str:
    roles = roles or ["Admin"]
    return jwt_codec.encode(
        subject=str(uuid4()),
        expires_in=timedelta(minutes=5),
        jti=new_jti(),
        claims={
            "principal_type": "USER",
            "role": roles,
            "permissions": sorted(permissions_for_roles(roles)),
        },
    )


def _register_device(app: FastAPI, *, enabled: bool = True) -> UUID:
    """Register a device through a self-contained event loop, before any TestClient opens."""
    device_id = uuid4()

    async def _create() -> None:
        database: Database = app.state.container.database()
        await database.create_schema_for_testing()
        async with database.session_factory() as session:
            repository = DeviceRepository(session)
            await repository.create(
                Device(
                    id=device_id,
                    device_name=f"agent-{device_id.hex[:8]}",
                    hostname=f"{device_id.hex[:8]}.local",
                    display_name="Test Agent",
                    status=DeviceStatus.REGISTERING,
                    enabled=enabled,
                    metadata_={},
                )
            )
            await session.commit()

    anyio.run(_create)
    return device_id


def _settle(client: TestClient, app: FastAPI, device_id: UUID, *, attempts: int = 30) -> None:
    """Give the server's own connection-cleanup task real time to finish.

    TestClient's websocket teardown cancels the server-side connection task
    rather than waiting for it to finish naturally. If that cancellation lands
    while the gateway's own disconnect cleanup is mid-flight (e.g. marking the
    device offline through the Application Layer), it can wedge aiosqlite's
    connection pool. Each ``client.get(...)`` below is a real synchronous
    round trip through the same portal thread the connection runs on, giving
    that cleanup task real turns to run to completion before anything else
    (including the test's own TestClient teardown) risks cancelling it.
    """
    session_manager = app.state.container.session_manager()
    for _ in range(attempts):
        client.get("/health")
        if session_manager.active_task_count == 0:
            return


def _hello(token: str, *, agent_version: str = "1.0.0", protocol_version: int = 1) -> str:
    return json.dumps(
        {
            "protocol_version": protocol_version,
            "message_type": "HELLO",
            "payload": {"token": token, "agent_version": agent_version},
        }
    )


def test_full_lifecycle_hello_welcome_event_ack_goodbye(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """A registered, enabled device completes the handshake and exchanges messages."""
    device_id = _register_device(app)
    token = _device_token(jwt_codec, device_id)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(_hello(token))
        welcome = json.loads(ws.receive_text())
        assert welcome["message_type"] == "WELCOME"
        assert welcome["payload"]["protocol_version"] == 1

        ws.send_text(
            json.dumps(
                {
                    "protocol_version": 1,
                    "message_type": "EVENT",
                    "payload": {"event_type": "sensor.tick", "data": {}},
                }
            )
        )
        ack = json.loads(ws.receive_text())
        assert ack["message_type"] == "MESSAGE_ACK"

        ws.send_text(json.dumps({"protocol_version": 1, "message_type": "GOODBYE", "payload": {}}))
        _settle(client, app, device_id)


def test_ping_receives_pong(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """The agent may also initiate a PING and receive a correlated PONG."""
    device_id = _register_device(app)
    token = _device_token(jwt_codec, device_id)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(_hello(token))
        ws.receive_text()  # WELCOME
        ws.send_text(json.dumps({"protocol_version": 1, "message_type": "PING", "payload": {}}))
        pong = json.loads(ws.receive_text())
        assert pong["message_type"] == "PONG"
        ws.send_text(json.dumps({"protocol_version": 1, "message_type": "GOODBYE", "payload": {}}))
        _settle(client, app, device_id)


def test_unregistered_device_is_rejected(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """A device token for a device that was never registered fails authentication."""
    token = _device_token(jwt_codec, uuid4())
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(_hello(token))
        ws.receive_text()
    assert exc_info.value.code == CloseCode.AUTHENTICATION_FAILED


def test_disabled_device_is_rejected(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """A device that exists but is disabled fails authentication even with a valid token."""
    device_id = _register_device(app, enabled=False)
    token = _device_token(jwt_codec, device_id)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(_hello(token))
        ws.receive_text()
    assert exc_info.value.code == CloseCode.AUTHENTICATION_FAILED


def test_a_user_token_cannot_connect_to_the_agent_gateway(
    app: FastAPI, jwt_codec: JWTCodec
) -> None:
    """Only device credentials may authenticate this gateway, never a human user token."""
    token = _user_token(jwt_codec)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(_hello(token))
        ws.receive_text()
    assert exc_info.value.code == CloseCode.AUTHENTICATION_FAILED


def test_an_invalid_token_is_rejected(app: FastAPI) -> None:
    """A malformed/unsigned token fails authentication rather than crashing the gateway."""
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(_hello("not-a-real-token"))
        ws.receive_text()
    assert exc_info.value.code == CloseCode.AUTHENTICATION_FAILED


def test_the_first_message_must_be_hello(app: FastAPI) -> None:
    """Sending anything other than HELLO first is a protocol violation."""
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(json.dumps({"protocol_version": 1, "message_type": "PING", "payload": {}}))
        ws.receive_text()
    assert exc_info.value.code == CloseCode.PROTOCOL_VIOLATION


def test_a_malformed_hello_payload_is_a_protocol_violation(app: FastAPI) -> None:
    """A HELLO payload missing its required token field fails validation."""
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(
            json.dumps(
                {
                    "protocol_version": 1,
                    "message_type": "HELLO",
                    "payload": {"agent_version": "1.0.0"},
                }
            )
        )
        ws.receive_text()
    assert exc_info.value.code == CloseCode.PROTOCOL_VIOLATION


def test_an_unsupported_protocol_version_is_rejected(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """A HELLO requesting an unsupported protocol version fails negotiation."""
    device_id = _register_device(app)
    token = _device_token(jwt_codec, device_id)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.send_text(_hello(token, protocol_version=999))
        ws.receive_text()
    assert exc_info.value.code == CloseCode.UNSUPPORTED_PROTOCOL_VERSION


def test_a_device_cannot_hold_two_open_sessions(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """A second connection for an already-connected device is rejected."""
    device_id = _register_device(app)
    token = _device_token(jwt_codec, device_id)
    with TestClient(app) as client, client.websocket_connect("/ws") as first:
        first.send_text(_hello(token))
        first.receive_text()  # WELCOME

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect("/ws") as second,
        ):
            second.send_text(_hello(token))
            second.receive_text()
        assert exc_info.value.code == CloseCode.DUPLICATE_SESSION

        first.send_text(
            json.dumps({"protocol_version": 1, "message_type": "GOODBYE", "payload": {}})
        )
        _settle(client, app, device_id)


def test_handshake_timeout_closes_a_silent_connection(app: FastAPI) -> None:
    """A connection that never sends HELLO is closed once the handshake window elapses."""
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_text()
    assert exc_info.value.code == CloseCode.HANDSHAKE_TIMEOUT


def test_session_is_removed_after_disconnect(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """After a client disconnects, its session no longer appears in the registry."""
    device_id = _register_device(app)
    token = _device_token(jwt_codec, device_id)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(_hello(token))
            ws.receive_text()  # WELCOME
            ws.send_text(
                json.dumps({"protocol_version": 1, "message_type": "GOODBYE", "payload": {}})
            )
            _settle(client, app, device_id)
        session_manager = app.state.container.session_manager()
        assert session_manager.get(device_id) is None
