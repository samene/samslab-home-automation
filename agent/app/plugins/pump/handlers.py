"""The one ``pump.*`` command handler: ``pump.trigger``.

There is deliberately no ``pump.stop`` — the Raspberry Pi never controls
watering duration, so there is nothing to stop. A timer relay wired to the
GPIO line owns the actual run time; this handler only ever fires one short
pulse to trigger it. Stateless, exactly like the built-in ``system.*``
handlers — everything it needs arrives through ``CommandContext``.
``PumpService.trigger`` does blocking I/O (a real ``time.sleep`` for the
pulse width), so this handler hands off to a thread-pool executor rather than
calling it directly on the event loop.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Mapping
from typing import Any

from app.commands.context import CommandContext
from app.commands.exceptions import CommandValidationError
from app.commands.handler import CommandHandler
from app.commands.registry import CommandRegistry
from app.plugins.pump.exceptions import PumpBusyError, PumpUnavailableError


class PumpTriggerHandler(CommandHandler):
    """Pulses the pump's GPIO line to fire the timer relay, then confirms it's back off."""

    @property
    def command_type(self) -> str:
        return "pump.trigger"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """``pulse_duration_ms`` is optional; if given, it must fall within the configured limits."""
        if "pulse_duration_ms" not in arguments:
            return
        value = arguments["pulse_duration_ms"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise CommandValidationError(
                "pulse_duration_ms must be an integer number of milliseconds"
            )
        settings = context.settings
        if not (settings.pump_trigger_pulse_min_ms <= value <= settings.pump_trigger_pulse_max_ms):
            raise CommandValidationError(
                "pulse_duration_ms must be between "
                f"{settings.pump_trigger_pulse_min_ms} and {settings.pump_trigger_pulse_max_ms}"
            )

    # The default 30s CommandHandler timeout is used as-is: even the largest
    # sane PUMP_TRIGGER_PULSE_MAX_MS (a real relay's trigger input never
    # needs to be held for more than a few seconds) leaves ample margin.

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        pump_service = context.services.pump_service
        pulse_duration_ms = arguments.get("pulse_duration_ms")
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        try:
            result = await loop.run_in_executor(
                None, functools.partial(pump_service.trigger, pulse_duration_ms=pulse_duration_ms)
            )
        except (PumpBusyError, PumpUnavailableError) as error:
            context.logger.warning(
                "pump_trigger_failed",
                command_id=str(context.command_id),
                correlation_id=str(context.correlation_id),
                gpio_pin=context.settings.pump_gpio_pin,
                pulse_duration_ms=pulse_duration_ms or context.settings.pump_trigger_pulse_ms,
                execution_duration=time.monotonic() - started,
                error=str(error),
            )
            raise
        context.logger.info(
            "pump_triggered",
            command_id=str(context.command_id),
            correlation_id=str(context.correlation_id),
            gpio_pin=result["gpio_pin"],
            pulse_duration_ms=result["pulse_duration_ms"],
            execution_duration=result["duration_seconds"],
        )
        return result


def register_pump_handlers(registry: CommandRegistry) -> None:
    """Register the ``pump.trigger`` handler onto ``registry``."""
    registry.register(PumpTriggerHandler())
