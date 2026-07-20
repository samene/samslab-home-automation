"""Where the pump's GPIO line is physically driven from.

``PumpGpioPort`` is the seam ``PumpService`` depends on — real hardware access
(``LgpioPumpGpio``) lives only behind this protocol, never imported by
``PumpService`` or a command handler directly. Tests inject a fake
implementation instead of touching real GPIO hardware.
"""

from __future__ import annotations

import contextlib
from typing import Protocol

from app.plugins.pump.exceptions import PumpUnavailableError


class PumpGpioPort(Protocol):
    """Something that can be opened, driven energized/de-energized, and closed."""

    def open(self) -> None:
        """Claim the line as an output, defaulting to its de-energized level; raise
        ``PumpUnavailableError`` on failure."""

    def set_energized(self, energized: bool) -> None:
        """Drive the line to its energized or de-energized level."""

    def close(self) -> None:
        """Release the line; safe to call even if never opened."""


class LgpioPumpGpio:
    """Drives one output line via ``lgpio``, the RP1-compatible GPIO library.

    Raspberry Pi 5 replaced the BCM283x GPIO controller earlier Pi models
    used with RP1, a separate southbridge chip reached over PCIe — the old
    ``RPi.GPIO`` library talks to BCM283x registers directly and cannot see
    RP1 at all, so it silently doesn't work on a Pi 5 (or fails outright).
    ``lgpio`` (and ``gpiozero``'s lgpio pin factory, which wraps the same
    library) instead goes through the kernel's ``/dev/gpiochip*`` character
    device interface, which RP1's kernel driver exposes identically to every
    earlier Pi's GPIO controller — this is what makes it the correct choice
    for Pi 5 compatibility rather than a raw register-mapped library.

    ``active_high`` decides which physical level counts as "energized": True
    (the common case for an active-high opto-isolated relay module) maps
    energized to physical HIGH; False (an active-low module) maps it to
    physical LOW. The de-energized/safe level is always the *other* one —
    computed here, once, rather than left to callers to get right per site.
    """

    def __init__(self, *, pin: int, active_high: bool, chip: int = 0) -> None:
        self._pin = pin
        self._active_high = active_high
        self._chip = chip
        self._handle: int | None = None

    def _level_for(self, *, energized: bool) -> int:
        physical_high = energized if self._active_high else not energized
        return 1 if physical_high else 0

    def open(self) -> None:
        try:
            import lgpio
        except ImportError as error:
            raise PumpUnavailableError(
                "lgpio is not installed; install the 'gpio' extra"
            ) from error

        try:
            handle = lgpio.gpiochip_open(self._chip)
            # Claim already at the de-energized level — there is never a
            # window, even at claim time, where the line could sit at its
            # energized level before the first explicit set_energized() call.
            lgpio.gpio_claim_output(handle, self._pin, self._level_for(energized=False))
        except Exception as error:
            raise PumpUnavailableError(
                f"Could not claim GPIO{self._pin} via lgpio: {error}"
            ) from error
        self._handle = handle

    def set_energized(self, energized: bool) -> None:
        if self._handle is None:
            raise PumpUnavailableError("GPIO line is not open")
        import lgpio

        try:
            lgpio.gpio_write(self._handle, self._pin, self._level_for(energized=energized))
        except Exception as error:
            raise PumpUnavailableError(
                f"Could not write GPIO{self._pin} via lgpio: {error}"
            ) from error

    def close(self) -> None:
        if self._handle is None:
            return
        import lgpio

        handle = self._handle
        self._handle = None
        with contextlib.suppress(Exception):
            lgpio.gpio_write(handle, self._pin, self._level_for(energized=False))
        with contextlib.suppress(Exception):
            lgpio.gpiochip_close(handle)
