"""Cron/one-time trigger validation and construction, shared by schemas.py and the Scheduler.

No new cron-parsing library: APScheduler's own ``CronTrigger.from_crontab``
both validates a cron string (raising ``ValueError`` on garbage input) and
computes the next fire time, so a separate library like ``croniter`` buys
nothing here. Keeping this logic in exactly one place means the 422 a bad
``POST /schedules`` gets and the trigger the live ``WorkflowScheduler``
actually registers can never drift apart.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.domains.schedules.models import ScheduleType


def validate_timezone(timezone: str) -> ZoneInfo:
    """Return the parsed IANA timezone, or raise ``ValueError`` if unknown."""
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"Unknown timezone '{timezone}'") from error


def validate_cron_expression(cron_expression: str, timezone: str) -> None:
    """Raise ``ValueError`` if ``cron_expression`` is not a valid 5-field crontab string."""
    tz = validate_timezone(timezone)
    try:
        CronTrigger.from_crontab(cron_expression, timezone=tz)
    except ValueError:
        raise
    except Exception as error:  # pragma: no cover - defensive, APScheduler always raises ValueError
        raise ValueError(f"Invalid cron expression '{cron_expression}': {error}") from error


def build_trigger(
    *,
    schedule_type: ScheduleType,
    cron_expression: str | None,
    run_at: datetime | None,
    timezone: str,
) -> BaseTrigger:
    """Build the APScheduler trigger a schedule's fields describe.

    Callers are expected to have already validated shape invariants (e.g.
    via ``ScheduleCreate``'s ``model_validator``) — this raises the same
    ``ValueError`` a bad cron expression or timezone would, so it's safe to
    call again here without duplicating that validation.
    """
    tz = validate_timezone(timezone)
    if schedule_type is ScheduleType.CRON:
        if not cron_expression:
            raise ValueError("cron_expression is required for a CRON schedule")
        return CronTrigger.from_crontab(cron_expression, timezone=tz)
    if run_at is None:
        raise ValueError("run_at is required for a ONE_TIME schedule")
    return DateTrigger(run_date=run_at, timezone=tz)
