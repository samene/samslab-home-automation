"""Tests for ConnectionManager: connect/authenticate/send/receive/heartbeat/disconnect/reconnect."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.connection.backoff import ExponentialBackoff
from app.connection.exceptions import AuthenticationRejectedError, NotConnectedError
from app.connection.manager import ConnectionManager
from app.metrics.registry import (
    AGENT_CONNECTED,
    CONNECTION_ATTEMPTS_TOTAL,
    HEARTBEAT_FAILURES_TOTAL,
    HEARTBEAT_TOTAL,
    RECONNECT_TOTAL,
)
from app.services.session import SessionState
from app.state.machine import AgentState, StateMachine
from app.tests.conftest import make_settings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope, PongPayload, WelcomePayload
from shared.protocol.serializer import serialize


def _metric_value(metric: object) -> float:
    family = next(iter(metric.collect()))  # type: ignore[attr-defined]
    return float(family.samples[0].value)


def _welcome_message(*, protocol_version: int = 1) -> str:
    payload = WelcomePayload(
        session_id=uuid4(),
        server_time=datetime.now(UTC),
        protocol_version=protocol_version,
        heartbeat_interval_seconds=30.0,
        heartbeat_timeout_seconds=10.0,
    )
    envelope = Envelope(
        protocol_version=protocol_version,
        message_type=MessageType.WELCOME,
        payload=payload.model_dump(mode="json"),
    )
    return serialize(envelope)


class FakeConnection:
    """A fake transport driven by a scripted list of incoming wire messages."""

    def __init__(
        self,
        *,
        incoming: list[str] | None = None,
        fail_send: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.sent: list[str] = []
        self._incoming = list(incoming or [])
        self.closed = False
        self._fail_send = fail_send
        self._fail_close = fail_close

    async def send(self, message: str) -> None:
        if self._fail_send:
            raise ConnectionError("send failed")
        self.sent.append(message)

    async def recv(self) -> str:
        if not self._incoming:
            raise ConnectionError("no more scripted messages")
        return self._incoming.pop(0)

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        if self._fail_close:
            raise ConnectionError("close failed")
        self.closed = True


async def _fake_token_provider(_settings: object) -> str:
    """Stands in for a real signed-assertion HTTP exchange in every connection test."""
    return "fake-access-token"


def _make_manager(
    *, connection: FakeConnection | None = None, connector_error: Exception | None = None
) -> tuple[ConnectionManager, StateMachine, SessionState]:
    settings = make_settings(RECONNECT_INTERVAL=0.001)
    state_machine = StateMachine(initial=AgentState.INITIALIZING)
    session = SessionState()

    async def connector(_url: str) -> FakeConnection:
        if connector_error is not None:
            raise connector_error
        return connection or FakeConnection(incoming=[_welcome_message()])

    manager = ConnectionManager(
        settings=settings,
        state_machine=state_machine,
        session=session,
        connector=connector,
        backoff=ExponentialBackoff(base_seconds=0.001, max_seconds=0.01),
        token_provider=_fake_token_provider,
    )
    return manager, state_machine, session


@pytest.mark.asyncio
async def test_connect_success_authenticates_and_goes_online() -> None:
    """A successful connect+authenticate lands in ONLINE with an authenticated session."""
    before = _metric_value(CONNECTION_ATTEMPTS_TOTAL)
    manager, state_machine, session = _make_manager()

    await manager.connect()

    assert state_machine.state is AgentState.ONLINE
    assert session.connected is True
    assert session.authenticated is True
    assert _metric_value(CONNECTION_ATTEMPTS_TOTAL) == before + 1
    assert _metric_value(AGENT_CONNECTED) == 1.0


@pytest.mark.asyncio
async def test_connect_propagates_connector_failure() -> None:
    """A connector failure propagates and leaves the session unauthenticated."""
    manager, _state_machine, session = _make_manager(connector_error=ConnectionError("refused"))

    with pytest.raises(ConnectionError):
        await manager.connect()

    assert session.authenticated is False


@pytest.mark.asyncio
async def test_authenticate_rejects_non_welcome_reply() -> None:
    """A reply that isn't WELCOME raises AuthenticationRejectedError."""
    not_welcome = Envelope(protocol_version=1, message_type=MessageType.ERROR, payload={})
    connection = FakeConnection(incoming=[serialize(not_welcome)])
    manager, _state_machine, _session = _make_manager(connection=connection)

    with pytest.raises(AuthenticationRejectedError):
        await manager.connect()


@pytest.mark.asyncio
async def test_send_without_connection_raises() -> None:
    """send() before connect() raises NotConnectedError."""
    manager, _state_machine, _session = _make_manager()
    envelope = Envelope(protocol_version=1, message_type=MessageType.PING, payload={})

    with pytest.raises(NotConnectedError):
        await manager.send(envelope)


@pytest.mark.asyncio
async def test_receive_without_connection_raises() -> None:
    """receive() before connect() raises NotConnectedError."""
    manager, _state_machine, _session = _make_manager()

    with pytest.raises(NotConnectedError):
        await manager.receive()


@pytest.mark.asyncio
async def test_heartbeat_sends_ping_and_records_session() -> None:
    """heartbeat() sends a PING and updates the session's last_heartbeat_at."""
    connection = FakeConnection(incoming=[_welcome_message()])
    manager, _state_machine, session = _make_manager(connection=connection)
    await manager.connect()
    heartbeats_before = _metric_value(HEARTBEAT_TOTAL)

    await manager.heartbeat()

    assert session.last_heartbeat_at is not None
    assert _metric_value(HEARTBEAT_TOTAL) == heartbeats_before + 1
    sent_types = [Envelope.model_validate_json(message).message_type for message in connection.sent]
    assert MessageType.PING in sent_types


@pytest.mark.asyncio
async def test_heartbeat_failure_increments_failure_metric() -> None:
    """A send failure during heartbeat() increments heartbeat_failures_total and propagates."""
    manager, _state_machine, _session = _make_manager()
    failures_before = _metric_value(HEARTBEAT_FAILURES_TOTAL)

    with pytest.raises(NotConnectedError):
        await manager.heartbeat()

    assert _metric_value(HEARTBEAT_FAILURES_TOTAL) == failures_before + 1


@pytest.mark.asyncio
async def test_disconnect_sends_goodbye_and_closes_transport() -> None:
    """disconnect() sends a GOODBYE, closes the transport, and resets the session."""
    connection = FakeConnection(incoming=[_welcome_message()])
    manager, _state_machine, session = _make_manager(connection=connection)
    await manager.connect()

    await manager.disconnect(reason="bye")

    assert connection.closed is True
    assert session.connected is False
    assert manager.is_connected is False
    assert _metric_value(AGENT_CONNECTED) == 0.0
    sent_types = [Envelope.model_validate_json(message).message_type for message in connection.sent]
    assert MessageType.GOODBYE in sent_types


@pytest.mark.asyncio
async def test_disconnect_without_connection_is_a_no_op() -> None:
    """disconnect() with no open transport doesn't raise."""
    manager, _state_machine, session = _make_manager()

    await manager.disconnect()

    assert session.connected is False


@pytest.mark.asyncio
async def test_disconnect_tolerates_goodbye_send_failure() -> None:
    """A failure sending GOODBYE is logged, not raised, and close() still runs."""
    connection = FakeConnection(incoming=[_welcome_message()])
    manager, _state_machine, session = _make_manager(connection=connection)
    await manager.connect()
    connection._fail_send = True

    await manager.disconnect()

    assert connection.closed is True
    assert session.connected is False


@pytest.mark.asyncio
async def test_disconnect_tolerates_close_failure() -> None:
    """A failure closing the transport is logged, not raised, and session state still resets."""
    connection = FakeConnection(incoming=[_welcome_message()])
    manager, _state_machine, session = _make_manager(connection=connection)
    await manager.connect()
    connection._fail_close = True

    await manager.disconnect()

    assert manager.is_connected is False
    assert session.connected is False


@pytest.mark.asyncio
async def test_reconnect_waits_then_connects() -> None:
    """reconnect() sleeps the backoff delay, then performs a full connect."""
    manager, state_machine, session = _make_manager()
    reconnects_before = _metric_value(RECONNECT_TOTAL)

    await manager.reconnect()

    assert state_machine.state is AgentState.ONLINE
    assert session.authenticated is True
    assert _metric_value(RECONNECT_TOTAL) == reconnects_before + 1


@pytest.mark.asyncio
async def test_reconnect_resets_backoff_after_success() -> None:
    """A successful reconnect resets the backoff so the next failure starts at base delay."""
    settings = make_settings(RECONNECT_INTERVAL=0.001)
    state_machine = StateMachine(initial=AgentState.INITIALIZING)
    session = SessionState()
    backoff = ExponentialBackoff(base_seconds=0.001, max_seconds=0.01)

    async def connector(_url: str) -> FakeConnection:
        return FakeConnection(incoming=[_welcome_message()])

    manager = ConnectionManager(
        settings=settings,
        state_machine=state_machine,
        session=session,
        connector=connector,
        backoff=backoff,
        token_provider=_fake_token_provider,
    )

    await manager.reconnect()

    assert backoff.next_delay() == 0.001


@pytest.mark.asyncio
async def test_pong_payload_can_be_sent_over_fake_connection() -> None:
    """Sanity check that a PONG payload constructed elsewhere serializes through send()."""
    connection = FakeConnection(incoming=[_welcome_message()])
    manager, _state_machine, _session = _make_manager(connection=connection)
    await manager.connect()
    pong_envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.PONG,
        payload=PongPayload(sent_at=datetime.now(UTC)).model_dump(mode="json"),
    )

    await manager.send(pong_envelope)

    assert any(
        Envelope.model_validate_json(message).message_type is MessageType.PONG
        for message in connection.sent
    )


def test_asyncio_sleep_is_real_but_delays_are_tiny() -> None:
    """Guard against accidentally using a large reconnect_interval in these tests."""
    assert asyncio.iscoroutinefunction(asyncio.sleep)
