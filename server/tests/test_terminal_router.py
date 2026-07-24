"""Direct TerminalGateway.handle_connection() tests using a scripted fake WebSocket.

Same rationale as test_websocket_gateway_direct.py: drives the gateway
directly on the single pytest-asyncio event loop rather than through
TestClient's separate-thread websocket portal — simpler and more reliable
for connection-internal edge cases (auth failures, device-unavailable,
multi-browser attach/reuse, mid-stream relay).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from app.application.events.bus import EventBus
from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.schemas import Principal, PrincipalType
from app.domains.auth.tokens import new_jti
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.terminal.manager import TerminalSessionManager
from app.terminal.router import TerminalGateway
from app.websocket.connection import Connection
from app.websocket.constants import CloseCode
from app.websocket.manager import SessionManager
from app.websocket.schemas import Envelope
from app.websocket.session import ConnectionState, Session

_JWT_SECRET = "a-sufficiently-long-test-signing-secret-value"


class _ScriptedWebSocket:
    """A minimal duck-typed WebSocket driven by a scripted sequence of incoming frames.

    See test_websocket_gateway_direct.py's identical helper for the full
    rationale (each item in ``incoming`` is returned in order by
    ``receive_text()``; once exhausted, either disconnects immediately or
    hangs until ``close()`` is called).
    """

    def __init__(
        self,
        incoming: list[str | Exception],
        *,
        hang_when_exhausted: bool = False,
    ) -> None:
        self._incoming = list(incoming)
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None
        self._hang_when_exhausted = hang_when_exhausted
        self._closed_event = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
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


def _jwt_codec(settings: Settings) -> JWTCodec:
    return JWTCodec(
        secret=settings.jwt_secret.get_secret_value(),  # type: ignore[union-attr]
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        clock_skew_seconds=settings.jwt_clock_skew_seconds,
    )


def _user_token(settings: Settings, *, roles: list[str] | None = None) -> str:
    roles = roles or ["Admin"]
    codec = _jwt_codec(settings)
    return codec.encode(
        subject="test-user",
        expires_in=timedelta(minutes=5),
        jti=new_jti(),
        claims={
            "principal_type": "USER",
            "role": roles,
            "permissions": sorted(permissions_for_roles(roles)),
        },
    )


def _device_token(settings: Settings, device_id: UUID) -> str:
    codec = _jwt_codec(settings)
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


def _hello_frame(token: str, *, protocol_version: int = 1) -> str:
    return json.dumps(
        {
            "protocol_version": protocol_version,
            "message_type": "HELLO",
            "payload": {"token": token, "agent_version": "browser/1.0.0"},
        }
    )


def _open_frame(*, cols: int = 80, rows: int = 24, session_id: UUID | None = None) -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "message_type": "TERMINAL_OPEN",
            "payload": {"session_id": str(session_id or uuid4()), "cols": cols, "rows": rows},
        }
    )


def _input_frame(data: str, *, session_id: UUID | None = None) -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "message_type": "TERMINAL_INPUT",
            "payload": {"session_id": str(session_id or uuid4()), "data": data},
        }
    )


def _close_frame(*, reason: str = "user_requested", session_id: UUID | None = None) -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "message_type": "TERMINAL_CLOSE",
            "payload": {"session_id": str(session_id or uuid4()), "reason": reason},
        }
    )


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
                status=DeviceStatus.ONLINE,
                enabled=enabled,
                metadata_={},
            )
        )
        await session.commit()
    return device_id


async def _build_env(
    settings: Settings,
) -> tuple[TerminalGateway, Database, SessionManager, TerminalSessionManager]:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_testing()
    event_bus = EventBus()
    session_manager = SessionManager()
    terminal_session_manager = TerminalSessionManager()
    gateway = TerminalGateway(
        settings=settings,
        database=database,
        event_bus=event_bus,
        session_manager=session_manager,
        terminal_session_manager=terminal_session_manager,
    )
    return gateway, database, session_manager, terminal_session_manager


async def _connect_agent(session_manager: SessionManager, device_id: UUID) -> Connection:
    agent_connection = Connection(
        SimpleNamespace(),  # type: ignore[arg-type]
        queue_size=50,
        ack_timeout_seconds=5.0,
        ack_max_retries=2,
    )
    now = datetime.now(UTC)
    session = Session(
        device_id=device_id,
        connection_id=uuid4(),
        connected_at=now,
        last_seen=now,
        protocol_version=1,
        authenticated_principal=Principal(
            principal_type=PrincipalType.DEVICE, subject_id=str(device_id), device_id=device_id
        ),
        connection=agent_connection,
        connection_state=ConnectionState.OPEN,
    )
    await session_manager.register(session)
    return agent_connection


@pytest.mark.asyncio
async def test_happy_path_opens_relays_input_and_confirms() -> None:
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    ws = _ScriptedWebSocket(
        [_hello_frame(token), _open_frame(cols=100, rows=30), _input_frame("ls\n")]
    )
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    welcome = json.loads(ws.sent[0])
    assert welcome["message_type"] == "WELCOME"
    assert terminal_manager.session_id_for(device_id) is not None
    await database.dispose()


@pytest.mark.asyncio
async def test_terminal_open_is_relayed_to_the_connected_agent() -> None:
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    agent_connection = await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    ws = _ScriptedWebSocket([_hello_frame(token), _open_frame(cols=100, rows=30)])
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    relayed = agent_connection._queue.get_nowait()  # noqa: SLF001
    assert relayed.message_type == "TERMINAL_OPEN"
    assert relayed.payload["cols"] == 100
    assert relayed.payload["rows"] == 30
    session_id = terminal_manager.session_id_for(device_id)
    assert relayed.payload["session_id"] == str(session_id)
    await database.dispose()


@pytest.mark.asyncio
async def test_input_is_relayed_with_the_authoritative_session_id() -> None:
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    agent_connection = await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    ws = _ScriptedWebSocket(
        [_hello_frame(token), _open_frame(), _input_frame("echo hi\n", session_id=uuid4())]
    )
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    agent_connection._queue.get_nowait()  # noqa: SLF001 - the TERMINAL_OPEN relay
    input_envelope = agent_connection._queue.get_nowait()  # noqa: SLF001
    assert input_envelope.message_type == "TERMINAL_INPUT"
    assert input_envelope.payload["data"] == "echo hi\n"
    assert input_envelope.payload["session_id"] == str(terminal_manager.session_id_for(device_id))
    await database.dispose()


@pytest.mark.asyncio
async def test_a_second_browser_reuses_the_open_session_without_a_second_open() -> None:
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    agent_connection = await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    first_ws = _ScriptedWebSocket([_hello_frame(token), _open_frame()])
    await gateway.handle_connection(first_ws, device_id)  # type: ignore[arg-type]
    session_id = terminal_manager.session_id_for(device_id)
    assert session_id is not None
    terminal_manager.mark_opened(device_id, session_id, "/bin/bash")
    # The shell already printed its prompt to the first (now-gone) browser —
    # simulates what relay.py's on_output records as it's produced.
    terminal_manager.append_output(device_id, "bash-5.2$ ")

    second_ws = _ScriptedWebSocket([_hello_frame(token), _open_frame()])
    await gateway.handle_connection(second_ws, device_id)  # type: ignore[arg-type]

    # Only the first browser's TERMINAL_OPEN should have reached the agent.
    opens = [
        envelope
        for envelope in _drain_all(agent_connection)
        if envelope.message_type == "TERMINAL_OPEN"
    ]
    assert len(opens) == 1
    # The second browser gets a synthesized TERMINAL_OPENED confirming reuse,
    # plus a replay of the buffered output — without this, it would just see
    # a blank screen and a blinking cursor, indistinguishable from "hung",
    # even though the session is alive and working (see
    # docs/agent/TERMINAL.md "Output replay on reattach").
    second_messages = [json.loads(frame) for frame in second_ws.sent]
    assert any(
        msg["message_type"] == "TERMINAL_OPENED" and msg["payload"]["shell"] == "/bin/bash"
        for msg in second_messages
    )
    assert any(
        msg["message_type"] == "TERMINAL_OUTPUT" and msg["payload"]["data"] == "bash-5.2$ "
        for msg in second_messages
    )
    await database.dispose()


@pytest.mark.asyncio
async def test_replayed_output_on_reattach_is_not_sent_to_already_attached_browsers() -> None:
    """The replay is targeted at the reattaching connection only — an
    already-attached browser has already seen this output and would see it
    duplicated if it were broadcast instead."""
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    first_ws = _ScriptedWebSocket([_hello_frame(token), _open_frame()], hang_when_exhausted=True)
    first_task = asyncio.create_task(
        gateway.handle_connection(first_ws, device_id)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.05)
    session_id = terminal_manager.session_id_for(device_id)
    assert session_id is not None
    terminal_manager.mark_opened(device_id, session_id, "/bin/bash")
    terminal_manager.append_output(device_id, "already seen by the first browser")
    sent_to_first_before = len(first_ws.sent)

    second_ws = _ScriptedWebSocket([_hello_frame(token), _open_frame()])
    await gateway.handle_connection(second_ws, device_id)  # type: ignore[arg-type]

    # The first (still-attached) browser received nothing further.
    assert len(first_ws.sent) == sent_to_first_before
    # The second (reattaching) browser got the replay.
    second_messages = [json.loads(frame) for frame in second_ws.sent]
    assert any(
        msg["message_type"] == "TERMINAL_OUTPUT"
        and msg["payload"]["data"] == "already seen by the first browser"
        for msg in second_messages
    )

    first_ws.closed = (1000, "test_teardown")
    first_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await first_task
    await database.dispose()


@pytest.mark.asyncio
async def test_no_replay_when_the_session_has_produced_no_output_yet() -> None:
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    first_ws = _ScriptedWebSocket([_hello_frame(token), _open_frame()])
    await gateway.handle_connection(first_ws, device_id)  # type: ignore[arg-type]
    session_id = terminal_manager.session_id_for(device_id)
    assert session_id is not None
    terminal_manager.mark_opened(device_id, session_id, "/bin/bash")

    second_ws = _ScriptedWebSocket([_hello_frame(token), _open_frame()])
    await gateway.handle_connection(second_ws, device_id)  # type: ignore[arg-type]

    second_messages = [json.loads(frame) for frame in second_ws.sent]
    assert not any(msg["message_type"] == "TERMINAL_OUTPUT" for msg in second_messages)
    await database.dispose()


def _drain_all(connection: Connection) -> list[Envelope]:
    items: list[Envelope] = []
    while not connection._queue.empty():  # noqa: SLF001
        items.append(connection._queue.get_nowait())
    return items


@pytest.mark.asyncio
async def test_rejects_a_device_credential() -> None:
    settings = _settings()
    gateway, database, session_manager, _terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    await _connect_agent(session_manager, device_id)
    device_token = _device_token(settings, device_id)

    ws = _ScriptedWebSocket([_hello_frame(device_token)])
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.AUTHENTICATION_FAILED, "authentication_failed")
    await database.dispose()


@pytest.mark.asyncio
async def test_rejects_a_user_without_the_required_permission() -> None:
    settings = _settings()
    gateway, database, session_manager, _terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    await _connect_agent(session_manager, device_id)
    token = _user_token(settings, roles=["Viewer"])

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.AUTHENTICATION_FAILED, "authentication_failed")
    await database.dispose()


@pytest.mark.asyncio
async def test_rejects_a_device_with_no_open_agent_session() -> None:
    settings = _settings()
    gateway, database, _session_manager, _terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    token = _user_token(settings)

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.DEVICE_UNAVAILABLE, "device_unavailable")
    await database.dispose()


@pytest.mark.asyncio
async def test_rejects_a_disabled_device() -> None:
    settings = _settings()
    gateway, database, session_manager, _terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database, enabled=False)
    await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.DEVICE_UNAVAILABLE, "device_unavailable")
    await database.dispose()


@pytest.mark.asyncio
async def test_an_unregistered_device_is_rejected() -> None:
    settings = _settings()
    gateway, database, _session_manager, _terminal_manager = await _build_env(settings)
    token = _user_token(settings)

    ws = _ScriptedWebSocket([_hello_frame(token)])
    await gateway.handle_connection(ws, uuid4())  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.DEVICE_UNAVAILABLE, "device_unavailable")
    await database.dispose()


@pytest.mark.asyncio
async def test_handshake_timeout_closes_the_connection() -> None:
    settings = _settings(WS_HELLO_TIMEOUT_SECONDS=0.05)
    gateway, database, _session_manager, _terminal_manager = await _build_env(settings)

    ws = _ScriptedWebSocket([], hang_when_exhausted=True)
    await gateway.handle_connection(ws, uuid4())  # type: ignore[arg-type]

    assert ws.closed == (CloseCode.HANDSHAKE_TIMEOUT, "handshake_timeout")
    await database.dispose()


@pytest.mark.asyncio
async def test_terminal_close_relays_to_the_agent_and_ends_the_connection() -> None:
    settings = _settings()
    gateway, database, session_manager, terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    agent_connection = await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    ws = _ScriptedWebSocket([_hello_frame(token), _open_frame(), _close_frame(reason="done")])
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    relayed = [
        envelope
        for envelope in _drain_all(agent_connection)
        if envelope.message_type == "TERMINAL_CLOSE"
    ]
    assert len(relayed) == 1
    assert relayed[0].payload["reason"] == "done"
    await database.dispose()


@pytest.mark.asyncio
async def test_malformed_message_is_ignored_not_fatal() -> None:
    settings = _settings()
    gateway, database, session_manager, _terminal_manager = await _build_env(settings)
    device_id = await _seed_device(database)
    await _connect_agent(session_manager, device_id)
    token = _user_token(settings)

    ws = _ScriptedWebSocket(
        [_hello_frame(token), _open_frame(), "not-json-at-all", _input_frame("ls\n")]
    )
    await gateway.handle_connection(ws, device_id)  # type: ignore[arg-type]

    # The connection should survive the garbage frame and keep processing.
    welcome = json.loads(ws.sent[0])
    assert welcome["message_type"] == "WELCOME"
    await database.dispose()
