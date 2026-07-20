"""Tests for LgpioPumpGpio: the lgpio-backed driver's polarity mapping and error paths.

A fake ``lgpio`` module is injected into ``sys.modules`` rather than
requiring the real library/hardware — mirrors
test_camera_sources.py's Picamera2FrameSource import-failure tests. No
Raspberry Pi or lgpio installation is required.
"""

from __future__ import annotations

import builtins
import sys
import types

import pytest

from app.plugins.pump.exceptions import PumpUnavailableError
from app.plugins.pump.gpio import LgpioPumpGpio


def _fake_import_raising(monkeypatch: pytest.MonkeyPatch, blocked_name: str) -> None:
    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == blocked_name:
            raise ImportError(f"No module named {blocked_name!r}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _fake_import)


def test_open_raises_when_lgpio_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_import_raising(monkeypatch, "lgpio")
    gpio = LgpioPumpGpio(pin=17, active_high=True)

    with pytest.raises(PumpUnavailableError, match="lgpio is not installed"):
        gpio.open()


def test_close_is_a_no_op_before_open() -> None:
    gpio = LgpioPumpGpio(pin=17, active_high=True)
    gpio.close()  # must not raise


def test_set_energized_raises_before_open() -> None:
    gpio = LgpioPumpGpio(pin=17, active_high=True)

    with pytest.raises(PumpUnavailableError, match="not open"):
        gpio.set_energized(True)


class _FakeLgpioModule:
    """A minimal stand-in for the real ``lgpio`` C-extension module."""

    def __init__(self) -> None:
        self.claimed: dict[int, int] = {}
        self.writes: list[tuple[int, int, int]] = []
        self.closed_handles: list[int] = []
        self._next_handle = 0

    def gpiochip_open(self, chip: int) -> int:
        self._next_handle += 1
        return self._next_handle

    def gpio_claim_output(self, handle: int, pin: int, level: int) -> None:
        self.claimed[pin] = level

    def gpio_write(self, handle: int, pin: int, level: int) -> None:
        self.writes.append((handle, pin, level))

    def gpiochip_close(self, handle: int) -> None:
        self.closed_handles.append(handle)


@pytest.fixture
def fake_lgpio(monkeypatch: pytest.MonkeyPatch) -> _FakeLgpioModule:
    fake = _FakeLgpioModule()
    module = types.SimpleNamespace(
        gpiochip_open=fake.gpiochip_open,
        gpio_claim_output=fake.gpio_claim_output,
        gpio_write=fake.gpio_write,
        gpiochip_close=fake.gpiochip_close,
    )
    monkeypatch.setitem(sys.modules, "lgpio", module)
    return fake


def test_active_high_energized_drives_the_pin_physically_high(fake_lgpio: _FakeLgpioModule) -> None:
    gpio = LgpioPumpGpio(pin=17, active_high=True)
    gpio.open()
    assert fake_lgpio.claimed[17] == 0  # claimed de-energized == physical LOW when active_high

    gpio.set_energized(True)
    assert fake_lgpio.writes[-1][1:] == (17, 1)

    gpio.set_energized(False)
    assert fake_lgpio.writes[-1][1:] == (17, 0)


def test_active_low_energized_drives_the_pin_physically_low(fake_lgpio: _FakeLgpioModule) -> None:
    gpio = LgpioPumpGpio(pin=17, active_high=False)
    gpio.open()
    assert fake_lgpio.claimed[17] == 1  # claimed de-energized == physical HIGH when active_low

    gpio.set_energized(True)
    assert fake_lgpio.writes[-1][1:] == (17, 0)

    gpio.set_energized(False)
    assert fake_lgpio.writes[-1][1:] == (17, 1)


def test_close_forces_de_energized_before_releasing_the_chip(fake_lgpio: _FakeLgpioModule) -> None:
    gpio = LgpioPumpGpio(pin=17, active_high=True)
    gpio.open()
    gpio.set_energized(True)

    gpio.close()

    assert fake_lgpio.writes[-1][1:] == (17, 0)
    assert len(fake_lgpio.closed_handles) == 1


def test_close_is_best_effort_when_the_chip_write_fails(fake_lgpio: _FakeLgpioModule) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("chip already gone")

    gpio = LgpioPumpGpio(pin=17, active_high=True)
    gpio.open()
    sys.modules["lgpio"].gpio_write = _raise  # type: ignore[attr-defined]

    gpio.close()  # must not raise despite the write failing

    assert len(fake_lgpio.closed_handles) == 1
