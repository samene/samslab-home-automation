"""The immutable bundle of dependencies a command handler receives at execution time.

A handler never reaches for a global — everything it needs (identifiers,
device metadata, configuration, a bound logger, metrics, and the application
services it's allowed to call) arrives through one ``CommandContext``, built
fresh for every command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import ModuleType
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.commands import metrics as command_metrics
from app.config.settings import AgentSettings
from app.health.service import HealthService
from app.plugins.camera.service import CameraService
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from shared.protocol.schemas import CommandPayload, Envelope

if TYPE_CHECKING:
    from app.commands.registry import CommandRegistry


@dataclass(frozen=True)
class CommandServices:
    """The application-layer services a handler is allowed to call.

    ``camera_service`` is the first hardware-adjacent domain service threaded
    through here (behind ``CameraService``'s own ``FrameSource``/
    ``StreamPublisher`` seams, never GPIO/OpenCV/ffmpeg directly); ``pump_service``
    follows the same pattern behind ``PumpService``'s own ``PumpGpioPort`` seam
    — a future scheduler service follows the same shape: add a field here,
    never have a handler import a hardware library directly.
    """

    plugin_manager: PluginManager
    health_service: HealthService
    registry: CommandRegistry
    agent_started_at: datetime
    camera_service: CameraService
    pump_service: PumpService


@dataclass(frozen=True)
class CommandContext:
    """Everything one command's ``validate()``/``execute()`` calls are given."""

    command_id: UUID
    command_type: str
    correlation_id: UUID | None
    trace_id: str | None
    device_name: str
    device_display_name: str | None
    agent_version: str
    settings: AgentSettings
    logger: Any
    metrics: ModuleType
    services: CommandServices


def build_command_context(
    *,
    envelope: Envelope,
    payload: CommandPayload,
    settings: AgentSettings,
    services: CommandServices,
    agent_version: str,
    logger: Any,
) -> CommandContext:
    """Build the per-command context from an incoming envelope and its parsed payload."""
    return CommandContext(
        command_id=payload.command_id,
        command_type=payload.command_type,
        correlation_id=envelope.correlation_id,
        trace_id=envelope.trace_id,
        device_name=settings.device_name,
        device_display_name=settings.device_display_name,
        agent_version=agent_version,
        settings=settings,
        logger=logger,
        metrics=command_metrics,
        services=services,
    )
