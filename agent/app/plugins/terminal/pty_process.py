"""Low-level PTY process spawning and control — the only place this plugin
touches ``pty``/``termios``/``fcntl``/``subprocess`` directly.

Deliberately not ``pty.fork()``: this agent is a multi-threaded asyncio
process (the camera plugin alone runs its frame pump on a background
thread), and ``fork()`` in a multi-threaded process only carries the forking
thread into the child — any lock another thread held at fork time can
deadlock the child forever. ``pty.openpty()`` + ``subprocess.Popen(...,
start_new_session=True)`` gives the same real controlling TTY (job control,
Ctrl+C/Ctrl+Z, SIGWINCH-on-resize all work exactly as they would over SSH)
without forking the agent process itself, and without the extra hazard of a
``preexec_fn`` (arbitrary Python running between fork and exec) that the
stdlib's own ``subprocess`` docs warn against in a threaded program —
``start_new_session`` does the equivalent ``setsid()`` safely in C, before
any Python re-enters the forked child.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass


@dataclass
class SpawnedPty:
    """One live PTY-backed shell process."""

    master_fd: int
    process: subprocess.Popen[bytes]


def spawn_pty(shell: str, *, cols: int, rows: int) -> SpawnedPty:
    """Open a PTY and spawn ``shell`` attached to its slave end as session leader."""
    master_fd, slave_fd = os.openpty()
    try:
        resize_pty(master_fd, cols=cols, rows=rows)
        child_env = dict(os.environ)
        child_env["TERM"] = "xterm-256color"
        try:
            process = subprocess.Popen(  # noqa: S603
                [shell],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=child_env,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)
    except BaseException:
        os.close(master_fd)
        raise
    os.set_blocking(master_fd, False)
    return SpawnedPty(master_fd=master_fd, process=process)


def resize_pty(master_fd: int, *, cols: int, rows: int) -> None:
    """Apply a new window size; the kernel delivers SIGWINCH to the foreground process group."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)


def terminate_pty(spawned: SpawnedPty, *, timeout: float = 2.0) -> int | None:
    """Kill the shell's whole process group, close the master fd, and reap the child.

    Signals the process *group* (not just the shell pid) so an interactive
    program the shell spawned (vim, top, a Python REPL) is also stopped —
    otherwise a lone foreground child can outlive its parent shell and
    become exactly the zombie/orphan this function exists to prevent.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(spawned.process.pid, signal.SIGTERM)
    try:
        spawned.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(spawned.process.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            spawned.process.wait(timeout=timeout)
    with contextlib.suppress(OSError):
        os.close(spawned.master_fd)
    return spawned.process.returncode
