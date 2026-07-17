"""Tests for systemd-friendly signal handling and directory setup."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from app.system.directories import ensure_directories
from app.system.signals import install_shutdown_handlers


def test_ensure_directories_creates_nested_paths(tmp_path: Path) -> None:
    """ensure_directories creates every path, including missing parents."""
    target = tmp_path / "a" / "b" / "c"

    ensure_directories([target])

    assert target.is_dir()


def test_ensure_directories_is_idempotent(tmp_path: Path) -> None:
    """Calling ensure_directories twice on the same path doesn't raise."""
    target = tmp_path / "already-there"
    target.mkdir()

    ensure_directories([target])

    assert target.is_dir()


async def test_install_shutdown_handlers_registers_signal_callback() -> None:
    """install_shutdown_handlers wires the callback to the given signals via the event loop."""
    loop = asyncio.get_running_loop()
    triggered = []

    install_shutdown_handlers(loop, lambda: triggered.append(True), signals=(signal.SIGUSR1,))

    try:
        os.kill(os.getpid(), signal.SIGUSR1)
        await asyncio.sleep(0.05)
        assert triggered == [True]
    finally:
        loop.remove_signal_handler(signal.SIGUSR1)
