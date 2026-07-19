"""In-memory registry of in-flight schedule-firing follow-up tasks.

A byte-for-byte copy of ``WorkflowRunRegistry``'s ``track()``/``wait_closed()``
shape — see that module's docstring for why this is the established pattern
for detached background work needing a shutdown drain hook. Tracks the
follow-up poller ``ScheduleApplicationService.execute_schedule`` spawns to
update a schedule's ``last_status`` once its triggered workflow run finishes,
never persisted: if interrupted by a restart, ``last_status`` simply stays
at its last-known value.
"""

from __future__ import annotations

import asyncio


class ScheduleRunRegistry:
    """Tracks every schedule-firing follow-up task so shutdown can wait for them."""

    def __init__(self) -> None:
        """Start empty; a fresh process always starts with zero in-flight follow-ups."""
        self._active_tasks: set[asyncio.Task[None]] = set()

    def track(self, task: asyncio.Task[None]) -> None:
        """Track one follow-up's own task so shutdown can wait for it to fully finish."""
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    @property
    def active_task_count(self) -> int:
        """Number of follow-up pollers still running."""
        return len(self._active_tasks)

    async def wait_closed(self, *, timeout: float = 30.0) -> None:
        """Wait for every tracked follow-up task to finish, bounded by ``timeout``."""
        tasks = list(self._active_tasks)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
