"""Tests for the Agent orchestrator: startup, reconnect-on-failure, dispatch, shutdown."""

from __future__ import annotations

import asyncio

import pytest

from app.dispatcher.dispatcher import MessageDispatcher
from app.lifecycle.orchestrator import Agent
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.state.machine import AgentState, StateMachine
from app.tests.conftest import make_settings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope


class FakeConnectionManager:
    """A fully fake ConnectionManager driven by a queue of incoming envelopes.

    Mirrors the real ConnectionManager's state-machine side effects (CONNECTING
    on attempt, AUTHENTICATING/ONLINE on success, no transition on failure —
    the orchestrator's own retry loop is responsible for moving to
    DISCONNECTED) so the orchestrator's transitions stay valid under test.
    """

    def __init__(
        self, *, state_machine: StateMachine, connect_results: list[Exception | None] | None = None
    ) -> None:
        self._state_machine = state_machine
        self.connect_calls = 0
        self.reconnect_calls = 0
        self.heartbeat_calls = 0
        self.disconnect_calls = 0
        self.sent: list[Envelope] = []
        self.on_failure: object | None = None
        self._connect_results = list(connect_results or [])
        self._incoming: asyncio.Queue[Envelope | Exception] = asyncio.Queue()

    def queue_incoming(self, envelope: Envelope) -> None:
        self._incoming.put_nowait(envelope)

    def queue_incoming_error(self, error: Exception) -> None:
        self._incoming.put_nowait(error)

    async def connect(self) -> None:
        self.connect_calls += 1
        self._state_machine.transition_to(AgentState.CONNECTING)
        if self._connect_results:
            result = self._connect_results.pop(0)
            if result is not None:
                if self.on_failure is not None:
                    self.on_failure()  # type: ignore[operator]
                raise result
        self._state_machine.transition_to(AgentState.AUTHENTICATING)
        self._state_machine.transition_to(AgentState.ONLINE)

    async def reconnect(self) -> None:
        self.reconnect_calls += 1
        await self.connect()

    async def heartbeat(self) -> None:
        self.heartbeat_calls += 1

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    async def receive(self) -> Envelope:
        item = await self._incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def disconnect(self, *, reason: str | None = None) -> None:
        self.disconnect_calls += 1


class RecordingPluginManager(PluginManager):
    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True


class FakeCommandDispatcher:
    """A no-op stand-in for ``CommandDispatcher`` — command runtime behavior has its own tests."""

    def __init__(self) -> None:
        self.handled: list[Envelope] = []
        self.closed = False

    async def handle_command(self, envelope: Envelope) -> None:
        self.handled.append(envelope)

    async def aclose(self) -> None:
        self.closed = True


def _make_agent(
    *,
    connect_results: list[Exception | None] | None = None,
    heartbeat_interval: float = 100.0,
) -> tuple[Agent, StateMachine, RecordingPluginManager, FakeConnectionManager, SessionState]:
    settings = make_settings(HEARTBEAT_INTERVAL=heartbeat_interval)
    state_machine = StateMachine()
    session = SessionState()
    dispatcher = MessageDispatcher()
    plugin_manager = RecordingPluginManager()
    connection_manager = FakeConnectionManager(
        state_machine=state_machine, connect_results=connect_results
    )
    agent = Agent(
        settings=settings,
        state_machine=state_machine,
        session=session,
        dispatcher=dispatcher,
        connection_manager=connection_manager,  # type: ignore[arg-type]
        plugin_manager=plugin_manager,
        command_dispatcher=FakeCommandDispatcher(),  # type: ignore[arg-type]
    )
    return agent, state_machine, plugin_manager, connection_manager, session


@pytest.mark.asyncio
async def test_agent_runs_starts_plugins_and_stops_on_goodbye() -> None:
    """A GOODBYE from the server ends the run loop and shuts everything down cleanly."""
    agent, state_machine, plugin_manager, connection_manager, _session = _make_agent()
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={"reason": "bye"})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert plugin_manager.started is True
    assert plugin_manager.stopped is True
    assert state_machine.state is AgentState.STOPPED
    assert connection_manager.disconnect_calls >= 1


@pytest.mark.asyncio
async def test_agent_reconnects_after_initial_connect_failure() -> None:
    """A failed first connect attempt is retried via reconnect() until it succeeds."""
    agent, _state_machine, _plugins, connection_manager, _session = _make_agent(
        connect_results=[ConnectionError("refused")]
    )
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert connection_manager.reconnect_calls == 1
    assert connection_manager.connect_calls == 2


@pytest.mark.asyncio
async def test_agent_responds_to_ping_with_pong() -> None:
    """A server-initiated PING is answered with a PONG via the connection manager."""
    agent, _state_machine, _plugins, connection_manager, _session = _make_agent()
    connection_manager.queue_incoming(
        Envelope(
            protocol_version=1,
            message_type=MessageType.PING,
            payload={"sent_at": "2026-01-01T00:00:00Z"},
        )
    )
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert any(envelope.message_type is MessageType.PONG for envelope in connection_manager.sent)


@pytest.mark.asyncio
async def test_agent_logs_server_error_without_stopping() -> None:
    """An ERROR message is logged but doesn't by itself end the run loop."""
    agent, _state_machine, _plugins, connection_manager, _session = _make_agent()
    connection_manager.queue_incoming(
        Envelope(
            protocol_version=1,
            message_type=MessageType.ERROR,
            payload={"code": "E1", "message": "boom"},
        )
    )
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert connection_manager.disconnect_calls >= 1


@pytest.mark.asyncio
async def test_agent_stops_immediately_if_requested_before_serving() -> None:
    """request_stop() called ahead of time short-circuits the heartbeat/receive loops."""
    agent, state_machine, plugin_manager, _connection_manager, _session = _make_agent()
    agent.request_stop()

    await asyncio.wait_for(agent.run(), timeout=5)

    assert state_machine.state is AgentState.STOPPED
    assert plugin_manager.stopped is True


@pytest.mark.asyncio
async def test_agent_sends_heartbeat_when_interval_elapses() -> None:
    """A short heartbeat_interval causes at least one heartbeat before shutdown."""
    agent, _state_machine, _plugins, connection_manager, _session = _make_agent(
        heartbeat_interval=0.01
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        connection_manager.queue_incoming(
            Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
        )

    stopper = asyncio.create_task(_stop_soon())
    await asyncio.wait_for(agent.run(), timeout=5)
    await stopper

    assert connection_manager.heartbeat_calls >= 1


@pytest.mark.asyncio
async def test_heartbeat_loop_exits_without_heartbeating_if_stopped_during_sleep() -> None:
    """If stop is requested while the heartbeat loop is sleeping, it exits without heartbeating."""
    agent, _state_machine, _plugins, connection_manager, _session = _make_agent(
        heartbeat_interval=0.02
    )

    async def _stop_during_sleep() -> None:
        await asyncio.sleep(0.005)
        agent.request_stop()

    stopper = asyncio.create_task(_stop_during_sleep())
    await agent._heartbeat_loop()
    await stopper

    assert connection_manager.heartbeat_calls == 0


@pytest.mark.asyncio
async def test_agent_records_heartbeat_ack_on_pong() -> None:
    """A PONG reply from the server is recorded on the session."""
    agent, _state_machine, _plugins, connection_manager, session = _make_agent()
    connection_manager.queue_incoming(
        Envelope(
            protocol_version=1,
            message_type=MessageType.PONG,
            payload={"sent_at": "2026-01-01T00:00:00Z"},
        )
    )
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert session.last_heartbeat_ack_at is not None


@pytest.mark.asyncio
async def test_ensure_connected_gives_up_if_stop_requested_during_retries() -> None:
    """If asked to stop while retrying, the agent gives up cleanly rather than looping forever."""
    agent, state_machine, _plugins, connection_manager, _session = _make_agent(
        connect_results=[ConnectionError("refused")]
    )
    connection_manager.on_failure = agent.request_stop

    await asyncio.wait_for(agent.run(), timeout=5)

    assert state_machine.state is AgentState.STOPPED
    assert connection_manager.connect_calls == 1
    assert connection_manager.reconnect_calls == 0


@pytest.mark.asyncio
async def test_ensure_connected_retries_through_multiple_reconnect_failures() -> None:
    """A reconnect() that itself fails is retried again rather than propagating."""
    agent, _state_machine, _plugins, connection_manager, _session = _make_agent(
        connect_results=[ConnectionError("a"), ConnectionError("b")]
    )
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert connection_manager.reconnect_calls == 2
    assert connection_manager.connect_calls == 3


@pytest.mark.asyncio
async def test_agent_recovers_from_connection_lost_during_receive() -> None:
    """A receive() failure (e.g. socket closed) is logged and triggers a reconnect."""
    agent, state_machine, _plugins, connection_manager, _session = _make_agent()
    connection_manager.queue_incoming_error(ConnectionError("dropped"))
    connection_manager.queue_incoming(
        Envelope(protocol_version=1, message_type=MessageType.GOODBYE, payload={})
    )

    await asyncio.wait_for(agent.run(), timeout=5)

    assert connection_manager.reconnect_calls == 1
    assert state_machine.state is AgentState.STOPPED
