"""Signal-driven graceful shutdown for running under systemd (``Restart=always``, SIGTERM)."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable

DEFAULT_SHUTDOWN_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)


def install_shutdown_handlers(
    loop: asyncio.AbstractEventLoop,
    callback: Callable[[], None],
    *,
    signals: tuple[signal.Signals, ...] = DEFAULT_SHUTDOWN_SIGNALS,
) -> None:
    """Call ``callback`` when the process receives any of ``signals``."""
    for sig in signals:
        loop.add_signal_handler(sig, callback)
