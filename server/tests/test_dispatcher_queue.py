"""Tests for DispatchQueue: priority ordering, FIFO within priority, and dedup."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.dispatcher.queue import DispatchQueue, QueuedCommand
from app.domains.commands.models import CommandPriority


def _item(priority: CommandPriority, *, command_id: UUID | None = None) -> QueuedCommand:
    return QueuedCommand(
        command_id=command_id or uuid4(),
        device_id=uuid4(),
        priority=priority,
        command_type="pump.start",
        payload={},
        enqueued_at=datetime.now(UTC),
    )


def test_pop_returns_none_when_empty() -> None:
    """An empty queue reports nothing to dispatch."""
    queue = DispatchQueue()
    assert queue.pop() is None
    assert len(queue) == 0


def test_priority_order_drains_critical_first() -> None:
    """CRITICAL drains before HIGH before NORMAL before LOW, regardless of push order."""
    queue = DispatchQueue()
    low = _item(CommandPriority.LOW)
    normal = _item(CommandPriority.NORMAL)
    high = _item(CommandPriority.HIGH)
    critical = _item(CommandPriority.CRITICAL)
    for item in (low, normal, high, critical):
        queue.push(item)
    assert queue.pop() is critical
    assert queue.pop() is high
    assert queue.pop() is normal
    assert queue.pop() is low
    assert queue.pop() is None


def test_fifo_order_within_the_same_priority() -> None:
    """Same-priority items drain in the order they were pushed."""
    queue = DispatchQueue()
    first = _item(CommandPriority.NORMAL)
    second = _item(CommandPriority.NORMAL)
    third = _item(CommandPriority.NORMAL)
    queue.push(first)
    queue.push(second)
    queue.push(third)
    assert queue.pop() is first
    assert queue.pop() is second
    assert queue.pop() is third


def test_push_rejects_a_duplicate_command_id() -> None:
    """A command already queued cannot be enqueued a second time."""
    queue = DispatchQueue()
    command_id = uuid4()
    first = _item(CommandPriority.NORMAL, command_id=command_id)
    duplicate = _item(CommandPriority.CRITICAL, command_id=command_id)
    assert queue.push(first) is True
    assert queue.push(duplicate) is False
    assert len(queue) == 1


def test_contains_reflects_queued_state() -> None:
    """contains() is true only while a command sits in the queue."""
    queue = DispatchQueue()
    item = _item(CommandPriority.NORMAL)
    assert queue.contains(item.command_id) is False
    queue.push(item)
    assert queue.contains(item.command_id) is True
    queue.pop()
    assert queue.contains(item.command_id) is False


def test_snapshot_reflects_priority_order_without_removing_items() -> None:
    """snapshot() previews dispatch order without mutating the queue."""
    queue = DispatchQueue()
    low = _item(CommandPriority.LOW)
    critical = _item(CommandPriority.CRITICAL)
    queue.push(low)
    queue.push(critical)
    assert queue.snapshot() == [critical, low]
    assert len(queue) == 2  # snapshot did not pop anything


def test_len_counts_distinct_queued_commands() -> None:
    """len() reflects the total across all priority lanes."""
    queue = DispatchQueue()
    queue.push(_item(CommandPriority.LOW))
    queue.push(_item(CommandPriority.CRITICAL))
    queue.push(_item(CommandPriority.CRITICAL))
    assert len(queue) == 3
