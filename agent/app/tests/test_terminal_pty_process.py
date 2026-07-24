"""Tests for the low-level PTY spawn/resize/terminate primitives.

Uses real ``/bin/sh`` processes (present on any POSIX box, including a
minimal CI container) rather than faking the OS layer — ``pty``/``fcntl``/
``subprocess`` are exactly what this module exists to wrap, so a fake here
would test nothing real.
"""

from __future__ import annotations

import fcntl
import os
import struct
import termios
import time

from app.plugins.terminal.pty_process import resize_pty, spawn_pty, terminate_pty


def _read_until(master_fd: int, expected: bytes, *, timeout: float = 2.0) -> bytes:
    """Poll the non-blocking master fd until ``expected`` shows up, or time out."""
    deadline = time.monotonic() + timeout
    collected = b""
    while time.monotonic() < deadline:
        try:
            chunk = os.read(master_fd, 65536)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        if not chunk:
            break
        collected += chunk
        if expected in collected:
            return collected
    raise AssertionError(f"Timed out waiting for {expected!r}; got {collected!r}")


def test_spawn_pty_runs_the_requested_shell_and_echoes_output() -> None:
    spawned = spawn_pty("/bin/sh", cols=80, rows=24)
    try:
        os.write(spawned.master_fd, b"echo hello-terminal\n")
        output = _read_until(spawned.master_fd, b"hello-terminal")
        assert b"hello-terminal" in output
    finally:
        terminate_pty(spawned)


def test_spawn_pty_applies_the_initial_window_size() -> None:
    spawned = spawn_pty("/bin/sh", cols=100, rows=40)
    try:
        raw = fcntl.ioctl(spawned.master_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, _x, _y = struct.unpack("HHHH", raw)
        assert (rows, cols) == (40, 100)
    finally:
        terminate_pty(spawned)


def test_resize_pty_updates_the_window_size() -> None:
    spawned = spawn_pty("/bin/sh", cols=80, rows=24)
    try:
        resize_pty(spawned.master_fd, cols=200, rows=50)
        raw = fcntl.ioctl(spawned.master_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, _x, _y = struct.unpack("HHHH", raw)
        assert (rows, cols) == (50, 200)
    finally:
        terminate_pty(spawned)


def test_terminate_pty_reaps_the_process_and_reports_its_exit_code() -> None:
    spawned = spawn_pty("/bin/sh", cols=80, rows=24)

    exit_code = terminate_pty(spawned)

    # SIGTERM (15) is what killpg sent; a shell with no trap exits with 128+signal.
    assert exit_code is not None
    assert spawned.process.poll() is not None


def test_terminate_pty_kills_a_process_that_ignores_sigterm() -> None:
    """A shell running a trap that swallows SIGTERM must still be reaped via SIGKILL."""
    spawned = spawn_pty("/bin/sh", cols=80, rows=24)
    os.write(spawned.master_fd, b"trap '' TERM\n")
    time.sleep(0.1)

    exit_code = terminate_pty(spawned, timeout=0.5)

    assert exit_code is not None
    assert spawned.process.poll() is not None
