#!/usr/bin/env python3.13
"""A lightweight developer CLI that verifies the whole distributed system end to end.

Starts a real (throwaway) Sam's Lab server, connects a real-protocol
``FakeAgent``, submits a handful of commands, waits for them to complete, and
prints timings and each command's server-side lifecycle event trail — no
hardware, no manually-started server, no test framework required.

Usage::

    python examples/verify_system.py
    python verify_system.py --verbose   # also show the server's own structured logs

See docs/development/INTEGRATION_TESTING.md for the full verification
framework this script is a thin, human-facing entry point into.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

# Make both the repo root (for `shared`/`tests`) and `server` (for `app`)
# importable regardless of the current working directory this is run from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (_REPO_ROOT, _REPO_ROOT / "server"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tests.fakes.fake_agent import FakeAgent  # noqa: E402
from tests.utils.logs import LogCapture  # noqa: E402
from tests.utils.server_harness import (  # noqa: E402
    ServerHarness,
    default_test_settings,
    run_server,
)
from tests.utils.waiters import WaitTimeoutError, wait_for_command_status  # noqa: E402

COMMANDS_TO_VERIFY: tuple[tuple[str, dict[str, Any]], ...] = (
    ("system.echo", {"message": "hello from verify_system.py"}),
    ("system.ping", {}),
    ("system.capabilities", {}),
    ("system.health", {}),
)

Printer = Callable[..., None]


async def _submit_and_verify(
    server: ServerHarness, device_id: UUID, command_type: str, payload: dict[str, Any]
) -> tuple[bool, float, dict[str, Any]]:
    started = time.monotonic()
    command_id = await server.create_command(device_id, command_type, payload=payload)
    try:
        final = await wait_for_command_status(server, command_id, "COMPLETED", timeout=10.0)
        return True, time.monotonic() - started, final
    except WaitTimeoutError:
        final = await server.get_command(command_id)
        return False, time.monotonic() - started, final


async def _run(out: Printer) -> int:
    title = "Sam's Lab — System Verification"
    out(f"\n{title}")
    out("=" * len(title))

    with tempfile.TemporaryDirectory() as tmp_dir:
        settings = default_test_settings(
            database_url=f"sqlite+aiosqlite:///{Path(tmp_dir) / 'verify_system.db'}"
        )

        step_started = time.monotonic()
        async with run_server(settings) as server:
            elapsed = time.monotonic() - step_started
            out(f"[1/4] Started server at {server.base_url} ({elapsed:.2f}s)")

            step_started = time.monotonic()
            device_id = await server.register_device(display_name="verify_system.py device")
            out(f"[2/4] Registered device {device_id} ({time.monotonic() - step_started:.2f}s)")

            step_started = time.monotonic()
            token = server.issue_device_token(device_id)
            agent = FakeAgent()
            welcome = await agent.connect(server.ws_url, token)
            out(
                f"[3/4] Connected fake agent, session {welcome.session_id} "
                f"({time.monotonic() - step_started:.2f}s)"
            )

            out("[4/4] Submitting commands:")
            all_ok = True
            total_started = time.monotonic()
            for command_type, payload in COMMANDS_TO_VERIFY:
                ok, duration, final = await _submit_and_verify(
                    server, device_id, command_type, payload
                )
                all_ok = all_ok and ok
                status_label = "OK  " if ok else "FAIL"
                out(
                    f"      [{status_label}] {command_type:<22} {duration * 1000:6.1f}ms  "
                    f"status={final['status']}"
                )
                lifecycle = " -> ".join(event["event_type"] for event in final["events"])
                out(f"             lifecycle: {lifecycle}")

            total_duration = time.monotonic() - total_started
            await agent.disconnect()

            admin_token = server.issue_user_token()
            stats = await server.dispatcher_statistics(admin_token)

        out("\nSummary")
        out("=======")
        out(f"{len(COMMANDS_TO_VERIFY)} command(s) submitted in {total_duration:.2f}s total")
        out(
            "Dispatcher statistics: "
            f"dispatched={stats['commands_dispatched_total']}, "
            f"retries={stats['dispatcher_retries_total']}, "
            f"timeouts={stats['dispatcher_timeouts_total']}"
        )
        if all_ok:
            out("\nResult: PASS — the whole system verified end to end.")
            return 0
        out("\nResult: FAIL — see the command(s) marked FAIL above.")
        return 1


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also print the server's own structured JSON logs",
    )
    args = parser.parse_args(argv)

    if args.verbose:
        return await _run(out=print)

    # Quiet by default: the server's own structured logs are captured (not
    # printed) so only this script's own step-by-step summary shows. `out`
    # is bound to the real stdout captured *before* redirecting, so this
    # script's own output is unaffected by that redirection.
    real_stdout = sys.stdout

    def out(*args: object) -> None:
        print(*args, file=real_stdout)

    with LogCapture():
        return await _run(out=out)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
