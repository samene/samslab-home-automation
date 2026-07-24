"""The one composition root: builds every subsystem and wires them into an ``Agent``.

Every dependency is constructed here and passed in — no subsystem reaches for
a global or constructs its own collaborators.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.commands.builtin import register_builtin_handlers
from app.commands.context import CommandServices
from app.commands.dispatcher import CommandDispatcher
from app.commands.events import CommandEventBus
from app.commands.executor import CommandExecutor
from app.commands.registry import CommandRegistry
from app.config.settings import AgentSettings
from app.connection.manager import ConnectionManager
from app.dispatcher.dispatcher import MessageDispatcher
from app.health.service import HealthService
from app.lifecycle.orchestrator import Agent
from app.plugins.camera.handlers import register_camera_handlers
from app.plugins.camera.plugin import CameraPlugin
from app.plugins.camera.service import CameraService
from app.plugins.pump.handlers import register_pump_handlers
from app.plugins.pump.plugin import PumpPlugin
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from app.plugins.terminal.plugin import TerminalPlugin
from app.plugins.terminal.service import TerminalService
from app.services.session import SessionState
from app.state.machine import StateMachine
from app.utils.version import AGENT_VERSION
from shared.protocol.message_types import MessageType


def build_agent(settings: AgentSettings, *, plugin_manager: PluginManager | None = None) -> Agent:
    """Compose a ready-to-run ``Agent`` from ``settings``."""
    state_machine = StateMachine()
    session = SessionState()
    dispatcher = MessageDispatcher()
    connection_manager = ConnectionManager(
        settings=settings, state_machine=state_machine, session=session
    )
    plugins = plugin_manager or PluginManager()
    camera_service = CameraService(settings)
    plugins.register(CameraPlugin(camera_service))
    pump_service = PumpService(settings)
    plugins.register(PumpPlugin(pump_service))
    terminal_service = TerminalService(settings, send=connection_manager.send)
    plugins.register(TerminalPlugin(terminal_service, enabled=settings.terminal_enabled))
    # TERMINAL_* messages are not commands (see app/plugins/terminal/service.py
    # for why) — registered straight onto the generic MessageDispatcher, the
    # same routing table PING/PONG/ERROR/GOODBYE use, rather than threaded
    # through CommandServices/CommandRegistry like a camera.* or pump.* handler.
    dispatcher.register(MessageType.TERMINAL_OPEN, terminal_service.handle_open)
    dispatcher.register(MessageType.TERMINAL_INPUT, terminal_service.handle_input)
    dispatcher.register(MessageType.TERMINAL_RESIZE, terminal_service.handle_resize)
    dispatcher.register(MessageType.TERMINAL_CLOSE, terminal_service.handle_close)
    health_service = HealthService(settings=settings, session=session, plugin_manager=plugins)

    registry = CommandRegistry()
    register_builtin_handlers(registry)
    register_camera_handlers(registry)
    register_pump_handlers(registry)
    command_dispatcher = CommandDispatcher(
        registry=registry,
        executor=CommandExecutor(),
        event_bus=CommandEventBus(),
        settings=settings,
        services=CommandServices(
            plugin_manager=plugins,
            health_service=health_service,
            registry=registry,
            agent_started_at=datetime.now(UTC),
            camera_service=camera_service,
            pump_service=pump_service,
        ),
        send=connection_manager.send,
        agent_version=AGENT_VERSION,
    )

    return Agent(
        settings=settings,
        state_machine=state_machine,
        session=session,
        dispatcher=dispatcher,
        connection_manager=connection_manager,
        plugin_manager=plugins,
        command_dispatcher=command_dispatcher,
    )


def build_health_service(
    settings: AgentSettings,
    *,
    session: SessionState | None = None,
    plugin_manager: PluginManager | None = None,
) -> HealthService:
    """Compose a standalone ``HealthService`` for a one-shot check (e.g. the CLI's ``health``)."""
    return HealthService(
        settings=settings,
        session=session or SessionState(),
        plugin_manager=plugin_manager or PluginManager(),
    )
