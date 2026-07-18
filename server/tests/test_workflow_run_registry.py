"""Tests for the in-memory WorkflowRunRegistry: tracking in-flight workflow-run tasks.

Mirrors ``test_websocket_manager.py``'s ``track``/``wait_closed`` tests exactly —
``WorkflowRunRegistry`` is modeled directly on ``SessionManager`` for this same
"detached background work with a shutdown drain hook" shape, just for one-shot
workflow-run tasks instead of long-lived WebSocket connection tasks.
"""

from __future__ import annotations

import asyncio

import pytest

from app.application.services.workflow_run_registry import WorkflowRunRegistry


@pytest.mark.asyncio
async def test_track_removes_the_task_from_active_count_once_it_finishes() -> None:
    """A tracked task that finishes on its own drops active_task_count back to zero."""
    registry = WorkflowRunRegistry()

    async def _quick() -> None:
        await asyncio.sleep(0.01)

    task = asyncio.create_task(_quick())
    registry.track(task)
    assert registry.active_task_count == 1
    await task
    await asyncio.sleep(0.01)  # let the done-callback run
    assert registry.active_task_count == 0


@pytest.mark.asyncio
async def test_wait_closed_is_a_no_op_with_no_tracked_tasks() -> None:
    """Waiting with nothing tracked returns immediately."""
    registry = WorkflowRunRegistry()
    await registry.wait_closed(timeout=1.0)


@pytest.mark.asyncio
async def test_wait_closed_waits_for_an_in_flight_task_to_finish() -> None:
    """A tracked task still running is awaited to completion, not cancelled early."""
    registry = WorkflowRunRegistry()
    completed = False

    async def _work() -> None:
        nonlocal completed
        await asyncio.sleep(0.05)
        completed = True

    task = asyncio.create_task(_work())
    registry.track(task)
    await registry.wait_closed(timeout=1.0)
    assert completed is True
    assert task.done()
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_wait_closed_cancels_a_task_that_outlives_the_timeout() -> None:
    """A tracked task still running past the timeout is forcibly cancelled."""
    registry = WorkflowRunRegistry()

    async def _forever() -> None:
        await asyncio.sleep(100)

    task = asyncio.create_task(_forever())
    registry.track(task)
    await registry.wait_closed(timeout=0.05)
    await asyncio.sleep(0.01)
    assert task.cancelled() or task.done()
