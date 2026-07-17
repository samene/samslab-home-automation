"""Wires the state machine, connection manager, plugin framework, health
subsystem, and command runtime into one running agent process.

Owns the two concurrent loops (heartbeat, receive) and the reconnect-on-failure
policy. Protocol handlers registered here are thin: PING/PONG/ERROR/GOODBYE
call back into the connection manager or session directly; COMMAND is handed
off whole to ``CommandDispatcher``, whose own processing task never blocks
these loops (see ``app/commands/dispatcher.py``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from app.commands.dispatcher import CommandDispatcher
from app.config.settings import AgentSettings
from app.connection.manager import ConnectionManager
from app.dispatcher.dispatcher import MessageDispatcher
from app.logging.configure import clear_context
from app.plugins.registry import PluginManager
from app.protocol.handlers import build_pong, parse_error, parse_goodbye, parse_ping
from app.services.session import SessionState
from app.state.machine import AgentState, StateMachine
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope

logger = structlog.get_logger(__name__)


class Agent:
    """The top-level orchestrator started by the CLI's ``start`` command."""

    def __init__(
        self,
        *,
        settings: AgentSettings,
        state_machine: StateMachine,
        session: SessionState,
        dispatcher: MessageDispatcher,
        connection_manager: ConnectionManager,
        plugin_manager: PluginManager,
        command_dispatcher: CommandDispatcher,
    ) -> None:
        self._settings = settings
        self._state_machine = state_machine
        self._session = session
        self._dispatcher = dispatcher
        self._connection_manager = connection_manager
        self._plugin_manager = plugin_manager
        self._command_dispatcher = command_dispatcher
        self._stopping = asyncio.Event()
        self._first_attempt = True
        self._register_protocol_handlers()

    def _register_protocol_handlers(self) -> None:
        async def handle_ping(envelope: Envelope) -> None:
            ping = parse_ping(envelope)
            pong = build_pong(protocol_version=self._settings.protocol_version, ping=ping)
            await self._connection_manager.send(pong)

        async def handle_pong(_: Envelope) -> None:
            self._session.record_heartbeat_ack(datetime.now(UTC))

        async def handle_error(envelope: Envelope) -> None:
            error = parse_error(envelope)
            logger.warning("agent.server_error", code=error.code, message=error.message)

        async def handle_goodbye(envelope: Envelope) -> None:
            goodbye = parse_goodbye(envelope)
            logger.info("agent.server_goodbye", reason=goodbye.reason)
            self._stopping.set()

        self._dispatcher.register(MessageType.PING, handle_ping)
        self._dispatcher.register(MessageType.PONG, handle_pong)
        self._dispatcher.register(MessageType.ERROR, handle_error)
        self._dispatcher.register(MessageType.GOODBYE, handle_goodbye)
        self._dispatcher.register(MessageType.COMMAND, self._command_dispatcher.handle_command)

    def request_stop(self) -> None:
        """Ask the running agent to shut down gracefully, e.g. from a signal handler."""
        self._stopping.set()

    async def run(self) -> None:
        """Start the agent and block until ``request_stop`` (or a GOODBYE) is honored."""
        self._state_machine.transition_to(AgentState.INITIALIZING)
        await self._plugin_manager.startup()
        while not self._stopping.is_set():
            connected = await self._ensure_connected()
            if not connected:
                break
            await self._serve_until_disconnected()
        await self._shutdown()

    async def _ensure_connected(self) -> bool:
        """Connect, retrying with backoff, until it succeeds or a stop is requested.

        Only the very first attempt of the process's lifetime is a bare
        ``connect()`` (immediate, no delay). Every attempt after that —
        whether the first one failed or a later established connection was
        lost — goes through ``reconnect()``, so a dropped connection always
        backs off rather than hot-looping.
        """
        connector = (
            self._connection_manager.connect
            if self._first_attempt
            else self._connection_manager.reconnect
        )
        self._first_attempt = False
        try:
            await connector()
            return True
        except Exception as error:
            logger.warning("agent.connect_failed", error=str(error))
            self._state_machine.transition_to(AgentState.DISCONNECTED)
        while not self._stopping.is_set():
            try:
                await self._connection_manager.reconnect()
                return True
            except Exception as error:
                logger.warning("agent.reconnect_failed", error=str(error))
                self._state_machine.transition_to(AgentState.DISCONNECTED)
        return False

    async def _serve_until_disconnected(self) -> None:
        """Run the heartbeat and receive loops until either ends (error or stop request)."""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        receive_task = asyncio.create_task(self._receive_loop())
        done, pending = await asyncio.wait(
            {heartbeat_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            error = task.exception()
            if error is not None:
                logger.warning("agent.connection_lost", error=str(error))
        await self._connection_manager.disconnect()
        if self._state_machine.state not in (AgentState.STOPPING, AgentState.STOPPED):
            self._state_machine.transition_to(AgentState.DISCONNECTED)

    async def _heartbeat_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(self._settings.heartbeat_interval)
            if self._stopping.is_set():
                return
            await self._connection_manager.heartbeat()

    async def _receive_loop(self) -> None:
        while not self._stopping.is_set():
            envelope = await self._connection_manager.receive()
            await self._dispatcher.dispatch(envelope)

    async def _shutdown(self) -> None:
        if self._state_machine.state not in (AgentState.STOPPING, AgentState.STOPPED):
            self._state_machine.transition_to(AgentState.STOPPING)
        await self._command_dispatcher.aclose()
        await self._connection_manager.disconnect(reason="agent shutting down")
        await self._plugin_manager.shutdown()
        self._state_machine.transition_to(AgentState.STOPPED)
        clear_context()
