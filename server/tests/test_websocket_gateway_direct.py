"""Direct WebSocketGateway.handle_connection() tests using a scripted fake WebSocket.

These bypass ``TestClient`` entirely: no ASGI portal thread, no cross-loop
aiosqlite access — everything runs on the single event loop pytest-asyncio
already manages for the test. This is deliberate: TestClient's websocket
support runs the ASGI app on a *separate* thread with its own event loop,
which both under-reports coverage for code that only runs there and, more
importantly, races the gateway's own DB writes against TestClient's teardown
cancellation (see test_websocket_gateway.py's ``_settle`` helper/docstring for
the full story). For gateway-internal edge cases — backpressure, mid-stream
protocol violations, duplicate messages, heartbeat timeouts closing a
connection — driving the gateway directly is both simpler and more reliable.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from app.application.dto.device_dto import DeviceDTO
from app.application.events.bus import EventBus
from app.application.exceptions import ConflictError
from app.application.services.device_service import DeviceApplicationService
from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.tokens import new_jti
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.websocket.connection import Connection
from app.websocket.constants import CloseCode
from app.websocket.gateway import WebSocketGateway
from app.websocket.manager import SessionManager
from app.websocket.protocol import MessageType
from app.websocket.schemas import Envelope
from app.websocket.serializer import serialize

_JWT_SECRET = "a-sufficiently-long-test-signing-secret-value"


class _ScriptedWebSocket:
    """A minimal duck-typed WebSocket driven by a scripted sequence of incoming frames.

    Each item in ``incoming`` is returned in order by ``receive_text()``; an
    ``Exception`` instance is raised instead of returned. Once the script is
    exhausted, either raises a disconnect immediately, or — if
    ``hang_when_exhausted`` — waits until ``close()`` is called (simulating a
    real connection sitting idle until the server closes it, e.g. after a
    heartbeat timeout) before raising the disconnect.
    """

    def __init__(
        self,
        incoming: list[str | Exception],
        *,
        client_host: str | None = "10.0.0.5",
        hang_when_exhausted: bool = False,
    ) -> None:
        self._incoming = list(incoming)
        self.client = SimpleNamespace(host=client_host) if client_host else None
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None
        self._hang_when_exhausted = hang_when_exhausted
        self._closed_event = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        # Real transports always involve at least one genuine suspension point;
        # yield here so sibling tasks (writer_loop, ack_watchdog_loop) actually
        # get scheduled between messages instead of being cancelled unrun.
        await asyncio.sleep(0)
        if self._incoming:
            item = self._incoming.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._hang_when_exhausted:
            await self._closed_event.wait()
        code, reason = self.closed or (1000, "")
        raise WebSocketDisconnect(code=code, reason=reason)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)
        self._closed_event.set()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "SERVER_NAME": "t",
        "ENVIRONMENT": Environment.TEST,
        "JWT_SECRET": _JWT_SECRET,
        "WS_HEARTBEAT_INTERVAL_SECONDS": 30.0,
        "WS_HEARTBEAT_TIMEOUT_SECONDS": 10.0,
        "WS_IDLE_TIMEOUT_SECONDS": 90.0,
        "WS_HELLO_TIMEOUT_SECONDS": 5.0,
        "WS_OUTGOING_QUEUE_SIZE": 10,
        "WS_MESSAGE_ACK_TIMEOUT_SECONDS": 5.0,
        "WS_MESSAGE_ACK_MAX_RETRIES": 2,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


async def _build_env(settings: Settings) -> tuple[WebSocketGateway, Database, SessionManager]:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_testing()
    event_bus = EventBus()
    session_manager = SessionManager()
    gateway = WebSocketGateway(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    return gateway, database, session_manager


async def _seed_device(database: Database, *, enabled: bool = True) -> UUID:
    device_id = uuid4()
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
    return device_id


def _device_token(settings: Settings, device_id: UUID) -> str:
    codec = JWTCodec(
        secret=settings.jwt_secret.get_secret_value(),  # type: ignore[union-attr]
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        clock_skew_seconds=settings.jwt_clock_skew_seconds,
    )
    return codec.encode(
        subject=str(device_id),
        expires_in=timedelta(minutes=5),
        jti=new_jti(),
        claims={
            "principal_type": "DEVICE",
            "role": ["Agent"],
            "permissions": sorted(permissions_for_roles(["Agent"])),
            "device_id": str(device_id),
        },
    )


def _hello_frame(token: str, *, agent_version: str = "1.0.0", protocol_version: int = 1) -> str:
    return json.dumps(
        {
            "protocol_version": protocol_version,
            "message_type": "HELLO",
            "payload": {"token": token, "agent_version": agent_version},
        }
    )


@pytest.mark.asyncio
async def test_backpressure_exceeded_during_welcome_closes_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full outgoing queue while sending WELCOME closes the connection, not the server."""
    settings = _settings()
    gateway, database, session_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _device_token(settings, device_id)

    from app.websocket.exceptions import BackpressureExceededError

    def _raising_enqueue(self: Connection, envelope: Envelope) -> None:
        raise BackpressureExceededError("full")

    monkeypatch.setattr(Connection, "enqueue", _raising_enqueue)

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.BACKPRESSURE, "backpressure_exceeded")
    assert session_manager.get(device_id) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_abrupt_disconnect_after_welcome_is_cleaned_up() -> None:
    """A client that vanishes without GOODBYE still triggers full session cleanup."""
    settings = _settings()
    gateway, database, session_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _device_token(settings, device_id)

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    welcome = json.loads(ws.sent[0])
    assert welcome["message_type"] == "WELCOME"
    assert session_manager.get(device_id) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_an_unregistered_device_fails_authentication_via_get_enabled_device() -> None:
    """A syntactically valid device token for a device that was never registered is rejected."""
    settings = _settings()
    gateway, database, _ = await _build_env(settings)
    token = _device_token(settings, uuid4())

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.AUTHENTICATION_FAILED, "authentication_failed")
    await database.dispose()


@pytest.mark.asyncio
async def test_jwt_not_configured_fails_the_handshake() -> None:
    """A HELLO cannot be authenticated if JWT signing was never configured."""
    settings = _settings(JWT_SECRET=None)
    gateway, database, _ = await _build_env(settings)

    ws = _ScriptedWebSocket([_hello_frame("irrelevant-token")])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.AUTHENTICATION_FAILED, "authentication_failed")
    await database.dispose()


@pytest.mark.asyncio
async def test_heartbeat_failures_while_marking_device_state_are_logged_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DeviceApplicationService failure while marking online/offline never crashes the connection."""
    settings = _settings()
    gateway, database, session_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _device_token(settings, device_id)

    async def _raising_heartbeat(
        self: DeviceApplicationService, *args: object, **kwargs: object
    ) -> DeviceDTO:
        raise ConflictError("simulated heartbeat failure")

    monkeypatch.setattr(DeviceApplicationService, "heartbeat", _raising_heartbeat)

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    welcome = json.loads(ws.sent[0])
    assert welcome["message_type"] == "WELCOME"
    assert session_manager.get(device_id) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_heartbeat_timeout_closes_an_unresponsive_connection() -> None:
    """A connection that never replies to PING is closed once the heartbeat window elapses."""
    settings = _settings(
        WS_HEARTBEAT_INTERVAL_SECONDS=0.02,
        WS_HEARTBEAT_TIMEOUT_SECONDS=0.02,
        WS_IDLE_TIMEOUT_SECONDS=10.0,
    )
    gateway, database, session_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _device_token(settings, device_id)

    ws = _ScriptedWebSocket([_hello_frame(token)], hang_when_exhausted=True)
    await asyncio.wait_for(gateway.handle_connection(ws), timeout=5.0)  # type: ignore[arg-type]

    assert ws.closed is not None
    assert ws.closed[0] == CloseCode.HEARTBEAT_TIMEOUT
    assert session_manager.get(device_id) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_a_protocol_violation_mid_conversation_closes_the_connection() -> None:
    """An invalid message sent after a successful handshake is a protocol violation."""
    settings = _settings()
    gateway, database, session_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _device_token(settings, device_id)

    ws = _ScriptedWebSocket([_hello_frame(token), "not valid json"])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.PROTOCOL_VIOLATION, "protocol_violation")
    assert session_manager.get(device_id) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_a_duplicate_message_id_is_skipped_not_reprocessed() -> None:
    """The same message_id sent twice is only dispatched (and acknowledged) once."""
    settings = _settings()
    gateway, database, session_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _device_token(settings, device_id)

    event_envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.EVENT,
        payload={"event_type": "sensor.tick", "data": {}},
    )
    event_frame = serialize(event_envelope)

    ws = _ScriptedWebSocket([_hello_frame(token), event_frame, event_frame])
    await gateway.handle_connection(ws)  # type: ignore[arg-type]

    ack_count = sum(1 for frame in ws.sent if json.loads(frame)["message_type"] == "MESSAGE_ACK")
    assert ack_count == 1
    assert session_manager.get(device_id) is None
    await database.dispose()
