"""The live trigger for Workflow Schedules — coordinates, never executes.

Mirrors ``CommandDispatcher``'s own ``start()``/``stop()`` shape
(``app/dispatcher/dispatcher.py``): idempotent start, graceful stop, and
zero knowledge of what a "workflow" or "command" even is beyond an opaque
``schedule_id`` handed to a caller-supplied ``on_fire`` callback. APScheduler
itself (a ``MemoryJobStore``-backed ``AsyncIOScheduler`` — deliberately not
its own ``SQLAlchemyJobStore``, which would need to pickle a callable/args
across restarts) does the actual "wait until next_run_time" work; this class
only registers/unregisters jobs and reloads them from the database at
startup, which *is* "Reload all enabled schedules automatically."
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import Database
from app.domains.schedules.models import Schedule
from app.domains.schedules.repository import ScheduleRepository
from app.domains.schedules.service import ScheduleService
from app.domains.schedules.validators import build_trigger
from app.scheduler.metrics import NEXT_SCHEDULE_TIMESTAMP

logger: Any = structlog.get_logger("scheduler")

OnFire = Callable[[UUID], Awaitable[None]]


class WorkflowScheduler:
    """Register/unregister live APScheduler jobs; delegates firing to ``on_fire``."""

    def __init__(self, *, database: Database | None) -> None:
        """Bind to the shared database used to reload schedules at startup."""
        self._database = database
        self._apscheduler: AsyncIOScheduler | None = None
        self._on_fire: OnFire | None = None
        self._started = False

    @property
    def is_running(self) -> bool:
        """Whether the live scheduler is currently accepting fires."""
        return self._started

    async def start(self, *, on_fire: OnFire) -> None:
        """Start the live scheduler and reload every enabled schedule; a no-op if already running."""
        if self._database is None:
            logger.warning("scheduler_not_started_no_database")
            return
        if self._started:
            return
        self._on_fire = on_fire
        self._apscheduler = AsyncIOScheduler(timezone="UTC")
        self._apscheduler.start()
        self._started = True
        schedules = await self._reload_enabled_schedules()
        for schedule in schedules:
            self.register(schedule)
        if schedules:
            await self._persist_next_run_times(schedules)
        logger.info("scheduler_started", reloaded_count=len(schedules))

    async def stop(self) -> None:
        """Stop taking new fires; a no-op if not running."""
        if not self._started or self._apscheduler is None:
            return
        self._apscheduler.shutdown(wait=False)
        self._apscheduler = None
        self._on_fire = None
        self._started = False
        logger.info("scheduler_stopped")

    def register(self, schedule: Schedule) -> None:
        """Add or replace this schedule's live job; a no-op before ``start()``."""
        if self._apscheduler is None:
            return
        trigger = build_trigger(
            schedule_type=schedule.schedule_type,
            cron_expression=schedule.cron_expression,
            run_at=schedule.run_at,
            timezone=schedule.timezone,
        )
        self._apscheduler.add_job(
            self._fire,
            trigger=trigger,
            id=str(schedule.id),
            args=[schedule.id],
            replace_existing=True,
            # APScheduler's own default (1 second) silently skips a fire if
            # more than that long has elapsed since it was due — easily
            # tripped by ordinary request latency between computing run_at
            # and this registration actually happening (confirmed live: a
            # ONE_TIME schedule a few seconds out never fired at all under
            # the default). None means "always fire, no matter how late" —
            # the right behavior for "run this workflow at this time", which
            # should never silently vanish just because it was briefly
            # delayed (e.g. a server restart or a slow request).
            misfire_grace_time=None,
        )
        self._refresh_next_run_metric()

    def unregister(self, schedule_id: UUID) -> None:
        """Remove a schedule's live job, tolerating "already gone" (e.g. a fired one-time job)."""
        if self._apscheduler is None:
            return
        with contextlib.suppress(JobLookupError):
            self._apscheduler.remove_job(str(schedule_id))
        self._refresh_next_run_metric()

    def next_run_time(self, schedule_id: UUID) -> datetime | None:
        """Return the live job's next fire time, or ``None`` if unregistered/not running."""
        if self._apscheduler is None:
            return None
        job = self._apscheduler.get_job(str(schedule_id))
        return job.next_run_time if job else None

    async def _reload_enabled_schedules(self) -> list[Schedule]:
        assert self._database is not None
        async with self._database.session_factory() as session:
            service = ScheduleService(ScheduleRepository(session))
            schedules = await service.list_enabled()
            await session.commit()
            return schedules

    async def _persist_next_run_times(self, schedules: list[Schedule]) -> None:
        """Refresh each reloaded schedule's stored next_run_at from its freshly-registered job.

        Without this, a schedule's displayed next_run_at would show whatever
        it was before this restart (potentially already in the past) until
        it next fires or is otherwise mutated through the application
        service — confirmed live against a real restart.
        """
        assert self._database is not None
        async with self._database.session_factory() as session:
            service = ScheduleService(ScheduleRepository(session))
            for schedule in schedules:
                await service.set_next_run_at(schedule.id, self.next_run_time(schedule.id))
            await session.commit()

    async def _fire(self, schedule_id: UUID) -> None:
        """The APScheduler job callback — delegates all business logic to ``on_fire``."""
        if self._on_fire is None:
            return
        try:
            await self._on_fire(schedule_id)
        except Exception as error:
            logger.warning(
                "scheduler_on_fire_failed", schedule_id=str(schedule_id), error=str(error)
            )
        finally:
            self._refresh_next_run_metric()

    def _refresh_next_run_metric(self) -> None:
        if self._apscheduler is None:
            NEXT_SCHEDULE_TIMESTAMP.set(0)
            return
        upcoming = [
            job.next_run_time
            for job in self._apscheduler.get_jobs()
            if job.next_run_time is not None
        ]
        NEXT_SCHEDULE_TIMESTAMP.set(min(upcoming).timestamp() if upcoming else 0)
