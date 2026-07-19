"""Structural (``Protocol``) contract the Schedules application service depends on.

Defined here, not imported from a concrete class, so tests can inject a fake
without a real ``AsyncIOScheduler`` — mirrors ``app.dispatcher.interfaces``'s
``DeviceSessionPort``/``CommandDeliveryPort`` split for the identical reason.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domains.schedules.models import Schedule


class SchedulerPort(Protocol):
    """The live-registration operations the Schedules application service needs."""

    def register(self, schedule: Schedule) -> None:
        """Add or replace this schedule's job in the live scheduler."""
        ...

    def unregister(self, schedule_id: UUID) -> None:
        """Remove a schedule's job from the live scheduler, tolerating "already gone"."""
        ...

    def next_run_time(self, schedule_id: UUID) -> datetime | None:
        """Return the live job's next fire time, or ``None`` if unregistered."""
        ...
