"""Poll-until-condition helpers for asserting on eventually-consistent server state.

Every real network/async round trip (dispatch, ack, execution, DB write) takes
some real wall-clock time; these helpers poll rather than sleep-then-assert,
so tests are both fast on a healthy run and not flaky under load.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from shared.protocol.message_types import MessageType
from tests.utils.server_harness import ServerHarness

if TYPE_CHECKING:
    from shared.protocol.schemas import Envelope
    from tests.fakes.fake_agent import FakeAgent


class WaitTimeoutError(AssertionError):
    """Raised when a polled condition never becomes true within the given timeout."""


async def wait_until(
    predicate: Callable[[], Awaitable[bool]],
    *,
    timeout: float = 5.0,
    interval: float = 0.02,
    description: str = "condition",
) -> None:
    """Poll ``predicate`` until it returns True, or raise after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(interval)
    raise WaitTimeoutError(f"Timed out after {timeout}s waiting for: {description}")


async def wait_for_value[T](
    fetch: Callable[[], Awaitable[T]],
    *,
    matches: Callable[[T], bool],
    timeout: float = 5.0,
    interval: float = 0.02,
    description: str = "value",
) -> T:
    """Poll ``fetch()`` until its result satisfies ``matches``; return that final value."""
    deadline = time.monotonic() + timeout
    last: T | None = None
    while time.monotonic() < deadline:
        last = await fetch()
        if matches(last):
            return last
        await asyncio.sleep(interval)
    raise WaitTimeoutError(
        f"Timed out after {timeout}s waiting for {description}; last value was {last!r}"
    )


async def wait_for_command_status(
    server: ServerHarness, command_id: UUID, expected: str, *, timeout: float = 5.0
) -> dict[str, Any]:
    """Poll ``GET /commands/{id}`` until its status matches ``expected``."""
    return await wait_for_value(
        lambda: server.get_command(command_id),
        matches=lambda command: command["status"] == expected,
        timeout=timeout,
        description=f"command {command_id} to reach status {expected}",
    )


async def wait_for_device_status(
    server: ServerHarness, device_id: UUID, expected: str, *, timeout: float = 5.0
) -> dict[str, Any]:
    """Poll ``GET /devices/{id}`` until its status matches ``expected``."""
    return await wait_for_value(
        lambda: server.get_device(device_id),
        matches=lambda device: device["status"] == expected,
        timeout=timeout,
        description=f"device {device_id} to reach status {expected}",
    )


async def wait_for_session(
    server: ServerHarness, admin_token: str, device_id: UUID, *, timeout: float = 5.0
) -> dict[str, Any]:
    """Poll ``GET /ws/sessions/{id}`` until the device has an active session."""

    async def fetch() -> dict[str, Any] | None:
        return await server.session_for(admin_token, device_id)

    result = await wait_for_value(
        fetch,
        matches=lambda session: session is not None,
        timeout=timeout,
        description=f"device {device_id} to have an active session",
    )
    assert result is not None
    return result


async def wait_for_no_session(
    server: ServerHarness, admin_token: str, device_id: UUID, *, timeout: float = 5.0
) -> None:
    """Poll ``GET /ws/sessions/{id}`` until the device no longer has a session."""
    await wait_until(
        lambda: _no_session(server, admin_token, device_id),
        timeout=timeout,
        description=f"device {device_id} to have no active session",
    )


async def _no_session(server: ServerHarness, admin_token: str, device_id: UUID) -> bool:
    return await server.session_for(admin_token, device_id) is None


async def wait_for_message(
    agent: FakeAgent,
    message_type: MessageType,
    *,
    since: int = 0,
    timeout: float = 5.0,
) -> Envelope:
    """Poll ``agent.received`` (filled by its background receive loop) for a message type.

    Never call ``agent.recv_envelope()`` concurrently with the background
    receive loop a connected ``FakeAgent`` already runs — the underlying
    ``websockets`` connection only allows one reader at a time. This is the
    safe way to observe a message the loop already consumed and reacted to.
    ``since`` skips the first N already-recorded messages (e.g. to look only
    at what arrived after a particular point in the test).
    """

    async def _has_message() -> bool:
        return any(
            envelope.message_type is message_type for envelope in agent.received[since:]
        )

    await wait_until(
        _has_message, timeout=timeout, description=f"a {message_type} message to arrive"
    )
    return next(
        envelope for envelope in agent.received[since:] if envelope.message_type is message_type
    )
