"""The pump plugin: lifecycle hooks that guarantee the GPIO line's safe-idle state."""

from __future__ import annotations

import asyncio

import structlog

from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.pump.service import PumpService

logger = structlog.get_logger(__name__)


class PumpPlugin(Plugin):
    """Advertises the ``pump`` capability and enforces GPIO safety at startup/shutdown.

    Safety is the highest priority for this plugin: the output must never be
    left energized. ``on_startup`` claims the line and immediately forces it
    to its de-energized level *before* anything else can touch it;
    ``on_shutdown`` forces it de-energized again and releases the line. Both
    run through ``PluginManager`` — ``on_startup`` before the agent ever
    connects, ``on_shutdown`` from ``Agent._shutdown()``, which runs on a
    server-initiated GOODBYE, a SIGTERM/SIGINT-driven graceful stop (see
    ``app/system/signals.py``), or the loop exiting for any other reason — so
    there is no shutdown path that skips forcing the line low.
    """

    name = "pump"
    capabilities = ("pump",)

    def __init__(self, pump_service: PumpService) -> None:
        self._pump_service = pump_service

    async def on_startup(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._pump_service.initialize)
        status = self._pump_service.status()
        if status["last_error"]:
            # initialize() is best-effort (see PumpService.initialize) — this
            # is logged, not raised, so a GPIO/permission failure degrades
            # only the pump capability rather than crashing agent startup
            # entirely (it would otherwise take camera/connectivity down
            # with it, since PluginManager.startup() has no per-plugin
            # error isolation).
            logger.error(
                "pump_gpio_initialization_failed",
                error=status["last_error"],
                gpio_pin=status["gpio_pin"],
            )
        else:
            logger.info("pump_gpio_initialized", gpio_pin=status["gpio_pin"])

    async def on_shutdown(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._pump_service.shutdown)
        status = self._pump_service.status()
        if status["last_error"]:
            logger.error("pump_gpio_shutdown_error", error=status["last_error"])
        else:
            logger.info("pump_gpio_forced_low")

    def check_health(self) -> PluginHealthCheck:
        """Healthy unless the last trigger/shutdown attempt actually failed."""
        status = self._pump_service.status()
        detail = (
            f"state={status['state']} total_triggers={status['total_triggers']} "
            f"last_trigger_at={status['last_trigger_at']}"
        )
        if status["last_error"]:
            return PluginHealthCheck(healthy=False, detail=status["last_error"])
        return PluginHealthCheck(healthy=True, detail=detail)
