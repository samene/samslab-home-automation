"""Failures raised by the camera plugin's own runtime, never a command-runtime exception.

A ``CameraUnavailableError`` is caught by the calling command handler's
``execute()`` propagating out normally — ``CommandExecutor`` already turns any
exception raised from a handler into a FAILED result, so this type exists only
to give that failure a specific, loggable name rather than a bare ``OSError``.
"""

from __future__ import annotations


class CameraUnavailableError(Exception):
    """Raised when the camera hardware or the MediaMTX publish process can't be started."""
