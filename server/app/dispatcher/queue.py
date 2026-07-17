"""An in-memory, priority-ordered queue of commands ready for a dispatch attempt.

CRITICAL drains before HIGH before NORMAL before LOW; within one priority,
insertion order is preserved (FIFO). This queue only orders *discovered*
commands between poll cycles — the durable priority ordering for discovery
itself is the repository's own ``find_pending`` query.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domains.commands.models import CommandPriority

#: Drain order: highest priority first.
_PRIORITY_ORDER: tuple[CommandPriority, ...] = (
    CommandPriority.CRITICAL,
    CommandPriority.HIGH,
    CommandPriority.NORMAL,
    CommandPriority.LOW,
)


@dataclass(frozen=True, slots=True)
class QueuedCommand:
    """Everything a dispatch attempt needs, captured once at discovery time."""

    command_id: UUID
    device_id: UUID
    priority: CommandPriority
    command_type: str
    payload: dict[str, Any]
    enqueued_at: datetime


class DispatchQueue:
    """A bounded-by-usage priority queue; never grows beyond distinct pending commands."""

    def __init__(self) -> None:
        """Start with one empty FIFO lane per priority."""
        self._lanes: dict[CommandPriority, deque[QueuedCommand]] = {
            priority: deque() for priority in CommandPriority
        }
        self._ids: set[UUID] = set()

    def push(self, item: QueuedCommand) -> bool:
        """Enqueue one command; a command already queued is never duplicated."""
        if item.command_id in self._ids:
            return False
        self._lanes[item.priority].append(item)
        self._ids.add(item.command_id)
        return True

    def pop(self) -> QueuedCommand | None:
        """Remove and return the next command in priority/FIFO order, or ``None`` if empty."""
        for priority in _PRIORITY_ORDER:
            lane = self._lanes[priority]
            if lane:
                item = lane.popleft()
                self._ids.discard(item.command_id)
                return item
        return None

    def contains(self, command_id: UUID) -> bool:
        """Return whether a command is currently queued."""
        return command_id in self._ids

    def snapshot(self) -> list[QueuedCommand]:
        """Return every queued command in priority/FIFO order, without removing any."""
        return [item for priority in _PRIORITY_ORDER for item in self._lanes[priority]]

    def __len__(self) -> int:
        """Total number of distinct commands currently queued, across all priorities."""
        return len(self._ids)
