"""Tests for PumpService: safe-idle guarantees, single-pulse triggering, and concurrency rejection.

Uses a fake PumpGpioPort implementation rather than real lgpio hardware —
mirrors CameraService's own FrameSource/StreamPublisher fakes in
test_camera_service.py. No Raspberry Pi or lgpio installation is required.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.plugins.pump.exceptions import PumpBusyError, PumpUnavailableError
from app.plugins.pump.service import PumpService
from app.tests.conftest import make_settings


class FakePumpGpio:
    """Records every energize/de-energize call; never touches real hardware."""

    def __init__(self, *, fail_to_open: bool = False, fail_on_energize: bool = False) -> None:
        self.opened = False
        self.closed = False
        self.energized_calls: list[bool] = []
        self._fail_to_open = fail_to_open
        self._fail_on_energize = fail_on_energize

    def open(self) -> None:
        if self._fail_to_open:
            raise PumpUnavailableError("gpio chip not found")
        self.opened = True

    def set_energized(self, energized: bool) -> None:
        if energized and self._fail_on_energize:
            raise PumpUnavailableError("write failed")
        self.energized_calls.append(energized)

    def close(self) -> None:
        self.closed = True


def _service(
    *, gpio: FakePumpGpio | None = None, **settings_overrides: object
) -> tuple[PumpService, FakePumpGpio]:
    fake = gpio or FakePumpGpio()
    settings = make_settings(**settings_overrides)
    service = PumpService(settings, gpio_factory=lambda: fake)
    return service, fake


def test_initialize_opens_and_forces_de_energized() -> None:
    service, gpio = _service()

    service.initialize()

    assert gpio.opened is True
    assert gpio.energized_calls == [False]


def test_initialize_is_best_effort_when_the_gpio_chip_cannot_be_opened() -> None:
    """A hardware/permission failure at startup must never raise out of initialize().

    Regression test: a real deployment hit this exact case (the systemd
    service user lacked the "gpio" group, so lgpio.gpiochip_open() raised)
    and, before this fix, PumpPlugin.on_startup() propagated the exception
    all the way through PluginManager.startup(), crashing the entire agent
    process — including camera and connectivity, not just the pump.
    """
    gpio = FakePumpGpio(fail_to_open=True)
    service, _gpio = _service(gpio=gpio)

    service.initialize()  # must not raise

    assert service.status()["last_error"] is not None
    assert service.status()["state"] == "Idle"


def test_trigger_reports_unavailable_when_gpio_was_never_opened() -> None:
    """After a failed initialize(), triggering fails loudly instead of silently succeeding.

    Mirrors LgpioPumpGpio's own real contract (see
    test_pump_gpio.py::test_set_energized_raises_before_open) — a
    FakePumpGpio that's already "opened" doesn't model this, so this test
    uses a minimal stand-in that does.
    """

    class _NeverOpensGpio:
        def open(self) -> None:
            raise PumpUnavailableError("gpio chip not found")

        def set_energized(self, energized: bool) -> None:
            raise PumpUnavailableError("GPIO line is not open")

        def close(self) -> None:
            pass

    settings = make_settings()
    service = PumpService(settings, gpio_factory=_NeverOpensGpio)
    service.initialize()

    with pytest.raises(PumpUnavailableError):
        service.trigger()


def test_shutdown_forces_de_energized_and_closes() -> None:
    service, gpio = _service()
    service.initialize()

    service.shutdown()

    assert gpio.energized_calls == [False, False]
    assert gpio.closed is True


def test_shutdown_is_best_effort_when_gpio_close_raises() -> None:
    class _RaisingCloseGpio(FakePumpGpio):
        def close(self) -> None:
            super().close()
            raise PumpUnavailableError("chip already released")

    service, gpio = _service(gpio=_RaisingCloseGpio())
    service.initialize()

    service.shutdown()  # must not raise

    assert gpio.closed is True
    assert service.status()["last_error"] is not None


def test_trigger_energizes_then_de_energizes_for_the_default_pulse() -> None:
    service, gpio = _service(PUMP_TRIGGER_PULSE_MS=50)
    service.initialize()
    gpio.energized_calls.clear()

    result = service.trigger()

    assert gpio.energized_calls == [True, False]
    assert result["pulse_duration_ms"] == 50
    assert result["gpio_pin"] == service.status()["gpio_pin"]
    assert result["duration_seconds"] >= 0.05


def test_trigger_honors_a_pulse_duration_override() -> None:
    service, gpio = _service(PUMP_TRIGGER_PULSE_MS=200)

    result = service.trigger(pulse_duration_ms=30)

    assert result["pulse_duration_ms"] == 30
    assert gpio.energized_calls == [True, False]


def test_trigger_updates_status_and_total_triggers() -> None:
    service, _gpio = _service(PUMP_TRIGGER_PULSE_MS=50)
    assert service.status()["state"] == "Idle"
    assert service.status()["total_triggers"] == 0

    service.trigger()

    status = service.status()
    assert status["state"] == "Idle"
    assert status["total_triggers"] == 1
    assert status["last_trigger_at"] is not None
    assert status["last_pulse_duration_ms"] == 50

    service.trigger()
    assert service.status()["total_triggers"] == 2


def test_trigger_force_de_energizes_even_when_energize_itself_raises() -> None:
    gpio = FakePumpGpio(fail_on_energize=True)
    service, _gpio = _service(gpio=gpio, PUMP_TRIGGER_PULSE_MS=50)

    with pytest.raises(PumpUnavailableError):
        service.trigger()

    # The energize call raised and was never recorded, but the de-energize
    # call in the finally block still ran — the line was never left high.
    assert gpio.energized_calls == [False]
    assert service.status()["last_error"] is not None
    assert service.status()["state"] == "Idle"


def test_trigger_is_usable_again_after_a_failed_attempt() -> None:
    gpio = FakePumpGpio(fail_on_energize=True)
    service, _gpio = _service(gpio=gpio, PUMP_TRIGGER_PULSE_MS=50)

    with pytest.raises(PumpUnavailableError):
        service.trigger()

    gpio._fail_on_energize = False
    result = service.trigger()

    assert result["pulse_duration_ms"] == 50
    assert service.status()["total_triggers"] == 1


def test_concurrent_trigger_is_rejected_without_blocking() -> None:
    service, _gpio = _service(PUMP_TRIGGER_PULSE_MS=200)
    started = threading.Event()
    finished = threading.Event()

    def _run_first() -> None:
        started.set()
        service.trigger()
        finished.set()

    thread = threading.Thread(target=_run_first)
    thread.start()
    started.wait(timeout=1)
    time.sleep(0.02)  # give the first trigger a moment to actually acquire the lock

    assert service.is_triggering is True
    with pytest.raises(PumpBusyError):
        service.trigger()

    thread.join(timeout=1)
    assert finished.is_set() is True
    assert service.status()["total_triggers"] == 1


def test_concurrent_rejection_does_not_touch_gpio() -> None:
    """A rejected trigger never energizes the line — only the in-flight one does."""
    service, gpio = _service(PUMP_TRIGGER_PULSE_MS=200)

    def _run_first() -> None:
        service.trigger()

    thread = threading.Thread(target=_run_first)
    thread.start()
    time.sleep(0.02)

    with pytest.raises(PumpBusyError):
        service.trigger()

    thread.join(timeout=1)
    # Exactly one energize/de-energize pair — the rejected call made no GPIO calls.
    assert gpio.energized_calls == [True, False]
