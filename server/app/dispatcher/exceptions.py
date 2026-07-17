"""Dispatcher-only failures; never a domain exception and never seen by REST directly."""

from __future__ import annotations


class DispatcherError(Exception):
    """Base error for every Command Dispatcher failure."""


class DeliveryFailedError(DispatcherError):
    """Raised when a connected device's outgoing queue rejects a command (backpressure).

    A device with no session at all is not exceptional — ``DeliveryService.is_device_connected``
    is the normal, expected way to check that before ever attempting to send.
    This is reserved for the narrower case: the device *is* connected, but its
    connection can't accept another message right now.
    """
