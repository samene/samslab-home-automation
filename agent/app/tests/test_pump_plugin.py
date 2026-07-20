"""Tests for PumpPlugin: startup/shutdown safety hooks and health reporting."""

from __future__ import annotations

import contextlib

from app.plugins.pump.plugin import PumpPlugin
from app.plugins.pump.service import PumpService
from app.tests.conftest import make_settings
from app.tests.test_pump_service import FakePumpGpio


def _plugin(*, gpio: FakePumpGpio | None = None) -> tuple[PumpPlugin, PumpService, FakePumpGpio]:
    fake = gpio or FakePumpGpio()
    settings = make_settings()
    service = PumpService(settings, gpio_factory=lambda: fake)
    return PumpPlugin(service), service, fake


def test_advertises_the_pump_capability() -> None:
    plugin, _service, _gpio = _plugin()
    assert plugin.name == "pump"
    assert "pump" in plugin.capabilities


async def test_on_startup_opens_gpio_and_forces_de_energized() -> None:
    plugin, _service, gpio = _plugin()

    await plugin.on_startup()

    assert gpio.opened is True
    assert gpio.energized_calls == [False]


async def test_on_startup_never_raises_when_gpio_cannot_be_opened() -> None:
    """Regression test for a real deployment failure.

    Before this fix, a GPIO/permission failure at startup (e.g. the systemd
    service user missing the "gpio" group, so lgpio.gpiochip_open() raised)
    propagated out of PumpPlugin.on_startup(), through
    PluginManager.startup() (which has no per-plugin error isolation), and
    crashed the entire agent process — taking camera and connectivity down
    with it, not just the pump. Startup must instead degrade only the pump
    capability.
    """
    gpio = FakePumpGpio(fail_to_open=True)
    plugin, service, _gpio = _plugin(gpio=gpio)

    await plugin.on_startup()  # must not raise

    assert service.status()["last_error"] is not None
    result = plugin.check_health()
    assert result.healthy is False


async def test_on_shutdown_forces_de_energized_and_closes() -> None:
    plugin, _service, gpio = _plugin()
    await plugin.on_startup()

    await plugin.on_shutdown()

    assert gpio.energized_calls == [False, False]
    assert gpio.closed is True


def test_check_health_is_healthy_when_idle_and_never_used() -> None:
    plugin, _service, _gpio = _plugin()

    result = plugin.check_health()

    assert result.healthy is True
    assert "state=Idle" in (result.detail or "")
    assert "total_triggers=0" in (result.detail or "")


def test_check_health_is_unhealthy_after_a_recorded_failure() -> None:
    gpio = FakePumpGpio(fail_on_energize=True)
    plugin, service, _gpio = _plugin(gpio=gpio)

    with contextlib.suppress(Exception):
        service.trigger()

    result = plugin.check_health()

    assert result.healthy is False
    assert result.detail == service.status()["last_error"]
