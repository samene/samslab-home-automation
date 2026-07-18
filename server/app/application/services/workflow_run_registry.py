"""In-memory registry of in-flight workflow-run background tasks.

Modeled directly on ``app/websocket/manager.py``'s ``SessionManager``
``track()``/``wait_closed()`` pair — the closest existing precedent for
"detached background work with a shutdown drain hook" in this codebase,
even though that one tracks WebSocket connection tasks rather than one-shot
workflow runs. Never persisted: a server restart drops every tracked task,
which is exactly why ``WorkflowService.reconcile_interrupted_runs`` exists
to fail any ``workflow_runs`` row left ``RUNNING`` with no owning task.
"""

from __future__ import annotations

import asyncio


class WorkflowRunRegistry:
    """Tracks every `run_workflow`-spawned task so shutdown can wait for them."""

    def __init__(self) -> None:
        """Start empty; a fresh process always starts with zero in-flight runs."""
        self._active_tasks: set[asyncio.Task[None]] = set()

    def track(self, task: asyncio.Task[None]) -> None:
        """Track one run's own task so shutdown can wait for it to fully finish."""
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    @property
    def active_task_count(self) -> int:
        """Number of workflow runs still executing."""
        return len(self._active_tasks)

    async def wait_closed(self, *, timeout: float = 30.0) -> None:
        """Wait for every tracked run task to finish, bounded by ``timeout``."""
        tasks = list(self._active_tasks)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
