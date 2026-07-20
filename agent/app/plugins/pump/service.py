"""Owns the pump's GPIO line and its single-pulse trigger lifecycle.

The Raspberry Pi never controls watering duration — a timer relay wired to
the GPIO line owns that. This service only ever does one thing: energize the
line, hold it for a configured number of milliseconds, then de-energize it
again. Driving the line is blocking (a real ``time.sleep`` for the pulse
width), so it runs on a background thread via the caller's own executor
offload — see ``app/plugins/pump/handlers.py`` — exactly like
``CameraService``'s frame pump. Only one pulse may run at a time; a second
``trigger()`` call while one is in flight is rejected immediately rather than
queued, since a pulse is always short (milliseconds, not seconds).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.config.settings import AgentSettings
from app.plugins.pump.exceptions import PumpBusyError
from app.plugins.pump.gpio import LgpioPumpGpio, PumpGpioPort
from app.plugins.pump.metrics import (
    PUMP_TRIGGER_DURATION_SECONDS,
    PUMP_TRIGGER_FAILURES_TOTAL,
    PUMP_TRIGGER_TOTAL,
)


class PumpService:
    """Owns the single GPIO line's safe-idle guarantee and trigger state."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        gpio_factory: Callable[[], PumpGpioPort] | None = None,
    ) -> None:
        self._settings = settings
        gpio_factory = gpio_factory or self._default_gpio
        self._gpio: PumpGpioPort = gpio_factory()
        self._lock = threading.Lock()
        self._triggering = False
        self._last_trigger_at: datetime | None = None
        self._last_pulse_duration_ms: int | None = None
        self._total_triggers = 0
        self._last_error: str | None = None

    def _default_gpio(self) -> PumpGpioPort:
        settings = self._settings
        return LgpioPumpGpio(pin=settings.pump_gpio_pin, active_high=settings.pump_active_high)

    @property
    def is_triggering(self) -> bool:
        """Whether a pulse is currently in flight."""
        return self._triggering

    def initialize(self) -> None:
        """Open the GPIO line and force it to its safe, de-energized state.

        Called once from ``PumpPlugin.on_startup`` — before anything else
        touches the line, it must already be settled at the non-triggering
        level, never left floating or at whatever level a prior process left
        it in.

        Best-effort, like ``shutdown()``: a hardware/permission failure here
        (a missing gpiochip, a udev/group misconfiguration, wrong chip index)
        must never prevent the rest of the agent from starting — an
        unreachable pump is one degraded capability, not a reason to also
        take down connectivity, the camera plugin, and everything else
        ``PluginManager`` manages (see ``app/plugins/registry.py``, which
        runs every plugin's ``on_startup`` with no per-plugin error
        isolation). The failure is recorded in ``last_error``/
        ``check_health()`` instead, and every subsequent ``trigger()`` call
        fails loudly with ``PumpUnavailableError`` — since the line was never
        actually opened — rather than silently pretending to succeed.
        """
        try:
            self._gpio.open()
            self._gpio.set_energized(False)
            self._last_error = None
        except Exception as error:
            self._last_error = str(error)

    def shutdown(self) -> None:
        """Force the line back to its safe, de-energized state and release it.

        Called from ``PumpPlugin.on_shutdown`` (normal shutdown, including a
        SIGTERM-driven graceful stop — see ``app/system/signals.py`` and
        ``app/lifecycle/orchestrator.py``'s ``_shutdown``). Best-effort by
        design: shutdown must never hang or raise just because the GPIO
        library itself is misbehaving on the way out.
        """
        try:
            self._gpio.set_energized(False)
        except Exception as error:  # pragma: no cover - defensive; logged by the caller
            self._last_error = str(error)
        try:
            self._gpio.close()
        except Exception as error:  # pragma: no cover - defensive; logged by the caller
            self._last_error = str(error)

    def trigger(self, *, pulse_duration_ms: int | None = None) -> dict[str, Any]:
        """Energize the line for ``pulse_duration_ms`` (or the configured default), then de-energize it.

        Raises ``PumpBusyError`` immediately, without blocking, if a pulse is
        already in flight — this is a rejection, not a queue. Whatever
        happens while the line is energized (a successful sleep, or an
        exception from the GPIO write itself), the line is always
        de-energized again before this method returns or raises — see the
        ``finally`` block below, which is the one place "never leave the
        output HIGH" is actually enforced for a triggered pulse.
        """
        if not self._lock.acquire(blocking=False):
            raise PumpBusyError("a pump trigger is already in progress")

        duration_ms = (
            pulse_duration_ms
            if pulse_duration_ms is not None
            else self._settings.pump_trigger_pulse_ms
        )
        self._triggering = True
        started = time.monotonic()
        try:
            try:
                self._gpio.set_energized(True)
                time.sleep(duration_ms / 1000)
            finally:
                self._gpio.set_energized(False)
        except Exception as error:
            self._last_error = str(error)
            PUMP_TRIGGER_FAILURES_TOTAL.inc()
            raise
        finally:
            self._triggering = False
            self._lock.release()

        elapsed = time.monotonic() - started
        triggered_at = datetime.now(UTC)
        self._last_trigger_at = triggered_at
        self._last_pulse_duration_ms = duration_ms
        self._total_triggers += 1
        self._last_error = None
        PUMP_TRIGGER_DURATION_SECONDS.observe(elapsed)
        PUMP_TRIGGER_TOTAL.inc()
        return {
            "gpio_pin": self._settings.pump_gpio_pin,
            "pulse_duration_ms": duration_ms,
            "triggered_at": triggered_at.isoformat(),
            "duration_seconds": elapsed,
        }

    def status(self) -> dict[str, Any]:
        """Current pump state without changing it — Idle/Triggering, last trigger, total triggers."""
        return {
            "state": "Triggering" if self._triggering else "Idle",
            "gpio_pin": self._settings.pump_gpio_pin,
            "last_trigger_at": self._last_trigger_at.isoformat() if self._last_trigger_at else None,
            "last_pulse_duration_ms": self._last_pulse_duration_ms,
            "total_triggers": self._total_triggers,
            "last_error": self._last_error,
        }
