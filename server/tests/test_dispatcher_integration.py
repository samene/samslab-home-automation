"""End-to-end Command Dispatcher tests: real WebSocketGateway, real DB, a reactive fake agent.

Everything here runs on the single event loop pytest-asyncio already manages
— no TestClient, no portal thread — for the same reasons
``test_websocket_gateway_direct.py`` does: it is both faster and avoids the
aiosqlite/cross-thread-cancellation hazard documented there.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.events.bus import EventBus
from app.config.settings import Environment, Settings
from app.core.database import Database
from app.dispatcher.dispatcher import CommandDispatcher
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.tokens import new_jti
from app.domains.commands.models import Command, CommandPriority, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.websocket.gateway import WebSocketGateway
from app.websocket.manager import SessionManager

_JWT_SECRET = "a-sufficiently-long-test-signing-secret-value"


class _FakeAgent:
    """A minimal duck-typed WebSocket driven by an async queue of incoming frames.

    Unlike the scripted fakes in ``test_websocket_gateway_direct.py``, this one
    is *reactive*: pushing an outgoing COMMAND envelope through ``send_text``
    can trigger ``on_command`` to enqueue reply frames (COMMAND_ACK,
    COMMAND_RESULT, ...), simulating a real agent's behavior.
    """

    def __init__(
        self,
        *,
        on_command: Callable[[dict[str, Any]], list[dict[str, Any]] | None] | None = None,
        client_host: str = "10.0.0.9",
    ) -> None:
        self._incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed: tuple[int, str] | None = None
        self.client = SimpleNamespace(host=client_host)
        self._on_command = on_command

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        return await self._incoming.get()

    async def push(self, frame: dict[str, Any]) -> None:
        await self._incoming.put(json.dumps(frame))

    async def send_text(self, data: str) -> None:
        envelope = json.loads(data)
        self.sent.append(envelope)
        if envelope["message_type"] == "COMMAND" and self._on_command is not None:
            replies = self._on_command(envelope) or []
            if replies:
                # A real agent replies after a real network round trip; without
                # this, an in-process reply can race ahead of the dispatcher's
                # own post-send bookkeeping (which involves an awaited DB write
                # that yields control to other tasks, including this one).
                await asyncio.sleep(0.03)
            for reply in replies:
                await self._incoming.put(json.dumps(reply))

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)

    def sent_command_ids(self) -> list[UUID]:
        return [
            UUID(envelope["payload"]["command_id"])
            for envelope in self.sent
            if envelope["message_type"] == "COMMAND"
        ]


def _ack_frame(command_id: UUID) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "message_type": "COMMAND_ACK",
        "payload": {"command_id": str(command_id)},
    }


def _result_frame(
    command_id: UUID, *, success: bool, error_message: str | None = None
) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "message_type": "COMMAND_RESULT",
        "payload": {
            "command_id": str(command_id),
            "success": success,
            "result": {"done": True} if success else {},
            "error_message": error_message,
        },
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(
        SERVER_NAME="Dispatcher Integration Test",
        ENVIRONMENT=Environment.TEST,
        JWT_SECRET=_JWT_SECRET,
        WS_HEARTBEAT_INTERVAL_SECONDS=30.0,
        WS_HEARTBEAT_TIMEOUT_SECONDS=10.0,
        WS_IDLE_TIMEOUT_SECONDS=90.0,
        WS_HELLO_TIMEOUT_SECONDS=5.0,
        WS_OUTGOING_QUEUE_SIZE=50,
        WS_MESSAGE_ACK_TIMEOUT_SECONDS=5.0,
        WS_MESSAGE_ACK_MAX_RETRIES=2,
        DISPATCHER_POLL_INTERVAL_SECONDS=0.03,
        DISPATCHER_SWEEP_INTERVAL_SECONDS=0.03,
        DISPATCHER_ACK_TIMEOUT_SECONDS=0.15,
        DISPATCHER_EXECUTION_TIMEOUT_SECONDS=0.2,
        DISPATCHER_MAX_RETRIES=2,
        DISPATCHER_RETRY_BACKOFF_BASE_SECONDS=0.05,
        DISPATCHER_RETRY_BACKOFF_MAX_SECONDS=0.2,
    )


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'dispatcher_integration.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def session_manager() -> SessionManager:
    return SessionManager()


async def _seed_device(database: Database, *, enabled: bool = True) -> UUID:
    async with database.session_factory() as session:
        repository = DeviceRepository(session)
        device = Device(
            device_name=f"agent-{uuid4().hex[:8]}",
            hostname="agent.local",
            display_name="Agent",
            status=DeviceStatus.REGISTERING,
            enabled=enabled,
            metadata_={},
        )
        await repository.create(device)
        await session.commit()
        return device.id


async def _create_command(
    database: Database,
    device_id: UUID,
    *,
    priority: CommandPriority = CommandPriority.NORMAL,
    max_retries: int = 0,
) -> UUID:
    async with database.session_factory() as session:
        service = CommandService(CommandRepository(session))
        command = await service.create_command(
            CommandCreate(
                device_id=device_id,
                command_type="pump.start",
                priority=priority,
                max_retries=max_retries,
            )
        )
        await session.commit()
        return command.id


async def _get_command(database: Database, command_id: UUID) -> Command:
    async with database.session_factory() as session:
        return await CommandService(CommandRepository(session)).get_command(command_id)


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


async def _connect_agent(
    settings: Settings,
    database: Database,
    event_bus: EventBus,
    session_manager: SessionManager,
    device_id: UUID,
    *,
    on_command: Callable[[dict[str, Any]], list[dict[str, Any]] | None] | None = None,
) -> tuple[_FakeAgent, asyncio.Task[None]]:
    """Authenticate and connect a fake agent; return it plus its running connection task."""
    agent = _FakeAgent(on_command=on_command)
    token = _device_token(settings, device_id)
    await agent.push(
        {
            "protocol_version": 1,
            "message_type": "HELLO",
            "payload": {"token": token, "agent_version": "1.0.0"},
        }
    )
    gateway = WebSocketGateway(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    task = asyncio.create_task(gateway.handle_connection(agent))  # type: ignore[arg-type]
    for _ in range(200):
        if any(e["message_type"] == "WELCOME" for e in agent.sent):
            break
        await asyncio.sleep(0.01)
    return agent, task


async def _disconnect_agent(agent: _FakeAgent, task: asyncio.Task[None]) -> None:
    """Send a graceful GOODBYE and wait for the connection task to finish on its own.

    ``handle_connection`` catches ``GoodbyeReceived`` internally and returns
    normally — it only raises ``WebSocketDisconnect`` for an abrupt transport
    drop, never for this graceful path.
    """
    await agent.push({"protocol_version": 1, "message_type": "GOODBYE", "payload": {}})
    await asyncio.wait_for(task, timeout=2.0)


async def _wait_for_status(
    database: Database, command_id: UUID, expected: CommandStatus, *, timeout: float = 3.0
) -> Command:
    deadline = asyncio.get_event_loop().time() + timeout
    last: Command | None = None
    while asyncio.get_event_loop().time() < deadline:
        last = await _get_command(database, command_id)
        if last.status is expected:
            return last
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"Command never reached {expected}; last status was {last and last.status}"
    )


@pytest.mark.asyncio
async def test_full_dispatch_ack_result_flow_completes_the_command(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """A connected device that acks and completes moves PENDING -> DISPATCHED -> RUNNING -> COMPLETED."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id)

    def on_command(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        cmd_id = UUID(envelope["payload"]["command_id"])
        return [_ack_frame(cmd_id), _result_frame(cmd_id, success=True)]

    agent, task = await _connect_agent(
        settings, database, event_bus, session_manager, device_id, on_command=on_command
    )
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        final = await _wait_for_status(database, command_id, CommandStatus.COMPLETED)
        assert final.result is not None
        assert final.result.success is True
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_a_failed_result_transitions_the_command_to_failed(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """An acked command whose result reports failure transitions to FAILED, not COMPLETED."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id)

    def on_command(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        cmd_id = UUID(envelope["payload"]["command_id"])
        return [
            _ack_frame(cmd_id),
            _result_frame(cmd_id, success=False, error_message="pump jammed"),
        ]

    agent, task = await _connect_agent(
        settings, database, event_bus, session_manager, device_id, on_command=on_command
    )
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        final = await _wait_for_status(database, command_id, CommandStatus.FAILED)
        assert final.result is not None
        assert final.result.error_message == "pump jammed"
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_a_disconnected_device_leaves_the_command_pending(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """With no device connected, a command is never dispatched and stays PENDING."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id)

    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        await asyncio.sleep(0.3)  # several poll cycles
        command = await _get_command(database, command_id)
        assert command.status is CommandStatus.PENDING
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_a_late_ack_after_the_command_has_already_failed_is_ignored(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """An ACK that arrives after retries are exhausted (already FAILED) does not resurrect it."""
    device_id = await _seed_device(database)
    # max_retries=0 on the dispatcher config (below) means the first ack timeout fails outright.
    command_id = await _create_command(database, device_id)

    # Connect an agent that never acks or replies to anything.
    agent, task = await _connect_agent(settings, database, event_bus, session_manager, device_id)
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        failed = await _wait_for_status(database, command_id, CommandStatus.FAILED, timeout=5.0)
        assert failed.result is not None

        # Now the "late" ack arrives — after the dispatcher already gave up.
        await agent.push(_ack_frame(command_id))
        await asyncio.sleep(0.2)

        still_failed = await _get_command(database, command_id)
        assert still_failed.status is CommandStatus.FAILED
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_duplicate_results_are_only_applied_once(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """A second COMMAND_RESULT for an already-completed command is dropped, not reapplied."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id)

    def on_command(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        cmd_id = UUID(envelope["payload"]["command_id"])
        return [
            _ack_frame(cmd_id),
            _result_frame(cmd_id, success=True),
            _result_frame(cmd_id, success=True),
        ]

    agent, task = await _connect_agent(
        settings, database, event_bus, session_manager, device_id, on_command=on_command
    )
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        final = await _wait_for_status(database, command_id, CommandStatus.COMPLETED)
        await asyncio.sleep(0.15)  # give the duplicate result time to (not) do anything
        still_final = await _get_command(database, command_id)
        assert still_final.status is CommandStatus.COMPLETED
        assert final.completed_at == still_final.completed_at
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_an_unacknowledged_command_is_retried_then_succeeds(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """The first delivery goes unacknowledged; the agent only acks the retried resend."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id, max_retries=2)
    attempts = {"count": 0}

    def on_command(envelope: dict[str, Any]) -> list[dict[str, Any]] | None:
        attempts["count"] += 1
        cmd_id = UUID(envelope["payload"]["command_id"])
        if attempts["count"] < 2:
            return None  # silently drop the first delivery
        return [_ack_frame(cmd_id), _result_frame(cmd_id, success=True)]

    agent, task = await _connect_agent(
        settings, database, event_bus, session_manager, device_id, on_command=on_command
    )
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        final = await _wait_for_status(database, command_id, CommandStatus.COMPLETED, timeout=5.0)
        assert final.retry_count >= 1
        assert attempts["count"] >= 2
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_a_running_command_with_no_result_times_out(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """A command acked but never given a result transitions to TIMEOUT."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id)

    def on_command(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        cmd_id = UUID(envelope["payload"]["command_id"])
        return [_ack_frame(cmd_id)]  # ack, but never send a result

    agent, task = await _connect_agent(
        settings, database, event_bus, session_manager, device_id, on_command=on_command
    )
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        final = await _wait_for_status(database, command_id, CommandStatus.TIMEOUT, timeout=5.0)
        assert final.completed_at is not None
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_priority_queue_dispatches_critical_before_normal(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """A CRITICAL command created after a NORMAL one is still dispatched first."""
    device_id = await _seed_device(database)
    normal_id = await _create_command(database, device_id, priority=CommandPriority.NORMAL)
    critical_id = await _create_command(database, device_id, priority=CommandPriority.CRITICAL)

    agent, task = await _connect_agent(settings, database, event_bus, session_manager, device_id)
    dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await dispatcher.start()
    try:
        for _ in range(200):
            if len(agent.sent_command_ids()) >= 2:
                break
            await asyncio.sleep(0.01)
        sent_ids = agent.sent_command_ids()
        assert sent_ids[0] == critical_id
        assert normal_id in sent_ids
    finally:
        await dispatcher.stop()
        await _disconnect_agent(agent, task)


@pytest.mark.asyncio
async def test_dispatcher_worker_lifecycle_survives_stop_and_restart(
    settings: Settings, database: Database, event_bus: EventBus, session_manager: SessionManager
) -> None:
    """Stopping and starting a fresh dispatcher instance against the same infra works cleanly."""
    device_id = await _seed_device(database)
    command_id = await _create_command(database, device_id)

    def on_command(envelope: dict[str, Any]) -> list[dict[str, Any]]:
        cmd_id = UUID(envelope["payload"]["command_id"])
        return [_ack_frame(cmd_id), _result_frame(cmd_id, success=True)]

    agent, task = await _connect_agent(
        settings, database, event_bus, session_manager, device_id, on_command=on_command
    )

    first_dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await first_dispatcher.start()
    assert first_dispatcher.is_running is True
    await first_dispatcher.stop()
    assert first_dispatcher.is_running is False

    second_dispatcher = CommandDispatcher(
        settings=settings, database=database, event_bus=event_bus, session_manager=session_manager
    )
    await second_dispatcher.start()
    try:
        final = await _wait_for_status(database, command_id, CommandStatus.COMPLETED, timeout=5.0)
        assert final.status is CommandStatus.COMPLETED
    finally:
        await second_dispatcher.stop()
        await _disconnect_agent(agent, task)
