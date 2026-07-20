"""Unit tests for cron/one-time trigger validation and construction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.domains.schedules.models import ScheduleType
from app.domains.schedules.validators import (
    build_trigger,
    validate_cron_expression,
    validate_timezone,
)


def test_validate_timezone_accepts_a_known_iana_name() -> None:
    validate_timezone("America/New_York")  # does not raise


def test_validate_timezone_accepts_a_legacy_iana_alias() -> None:
    """ "Asia/Calcutta" (superseded by "Asia/Kolkata") is what browsers still return from
    Intl.supportedValuesOf("timeZone") in some cases, so the frontend's timezone dropdown
    can offer it — the backend must resolve it too, not just the modern canonical name.
    This requires the tzdata PyPI package: a minimal container's system tzdata often
    omits deprecated backward-compatibility aliases even though it has the modern name.
    """
    validate_timezone("Asia/Calcutta")  # does not raise


def test_validate_timezone_rejects_an_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown timezone"):
        validate_timezone("Not/AZone")


@pytest.mark.parametrize(
    "expression",
    ["*/5 * * * *", "0 0 * * 0", "0 9-17 * * 1-5", "0 0 1 1 *"],
)
def test_validate_cron_expression_accepts_valid_crontab_strings(expression: str) -> None:
    validate_cron_expression(expression, "UTC")  # does not raise


@pytest.mark.parametrize(
    "expression",
    ["not a cron", "* * * *", "60 * * * *", ""],
)
def test_validate_cron_expression_rejects_invalid_crontab_strings(expression: str) -> None:
    with pytest.raises(ValueError):
        validate_cron_expression(expression, "UTC")


def test_validate_cron_expression_rejects_an_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="Unknown timezone"):
        validate_cron_expression("* * * * *", "Not/AZone")


def test_build_trigger_returns_a_cron_trigger_for_cron_schedules() -> None:
    trigger = build_trigger(
        schedule_type=ScheduleType.CRON, cron_expression="*/5 * * * *", run_at=None, timezone="UTC"
    )
    assert isinstance(trigger, CronTrigger)


def test_build_trigger_returns_a_date_trigger_for_one_time_schedules() -> None:
    run_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    trigger = build_trigger(
        schedule_type=ScheduleType.ONE_TIME, cron_expression=None, run_at=run_at, timezone="UTC"
    )
    assert isinstance(trigger, DateTrigger)


def test_build_trigger_raises_when_cron_expression_is_missing_for_a_cron_schedule() -> None:
    with pytest.raises(ValueError, match="cron_expression is required"):
        build_trigger(
            schedule_type=ScheduleType.CRON, cron_expression=None, run_at=None, timezone="UTC"
        )


def test_build_trigger_raises_when_run_at_is_missing_for_a_one_time_schedule() -> None:
    with pytest.raises(ValueError, match="run_at is required"):
        build_trigger(
            schedule_type=ScheduleType.ONE_TIME, cron_expression=None, run_at=None, timezone="UTC"
        )


def test_build_trigger_computes_a_next_fire_time_for_a_cron_schedule() -> None:
    trigger = build_trigger(
        schedule_type=ScheduleType.CRON, cron_expression="*/5 * * * *", run_at=None, timezone="UTC"
    )
    next_fire = trigger.get_next_fire_time(None, datetime.now(UTC))
    assert next_fire is not None
    assert next_fire.minute % 5 == 0
