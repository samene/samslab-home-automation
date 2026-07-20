"""Failures raised by the pump plugin's own runtime, never a command-runtime exception.

Caught by the calling command handler's ``execute()``, propagating out
normally — ``CommandExecutor`` already turns any exception raised from a
handler into a FAILED result, so these types exist only to give a failure a
specific, loggable name.
"""

from __future__ import annotations


class PumpUnavailableError(Exception):
    """Raised when the GPIO line can't be opened, claimed, or written."""


class PumpBusyError(Exception):
    """Raised when a trigger is requested while another is already in progress.

    Concurrent triggers are rejected outright, never queued — pulses are
    short enough that a caller can simply retry.
    """
