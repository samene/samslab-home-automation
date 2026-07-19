"""Process-global Prometheus metrics for Workflow Schedules.

Module-level ``Counter``/``Gauge`` objects, the same deliberate, narrow
exception to "no module-level singletons" already established in
``app.websocket.metrics``/``app.dispatcher.metrics`` — metrics are
conventionally process-global, defined once at import time, and safe to
share across every ``create_app()`` instance built in the same process
(e.g. one per test).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

SCHEDULES_TOTAL = Gauge("schedules_total", "Total number of active (non-deleted) schedules")
ENABLED_SCHEDULES = Gauge("enabled_schedules", "Number of schedules currently enabled")
SCHEDULE_EXECUTIONS_TOTAL = Counter(
    "schedule_executions_total", "Total times a schedule successfully triggered a workflow run"
)
SCHEDULE_FAILURES_TOTAL = Counter(
    "schedule_failures_total", "Total times a schedule fired but failed to trigger a workflow run"
)
NEXT_SCHEDULE_TIMESTAMP = Gauge(
    "next_schedule_timestamp", "Unix timestamp of the soonest next_run_at across enabled schedules"
)


def read_gauge(gauge: Gauge) -> float:
    """Read a Gauge's current value.

    ``prometheus_client`` has no public getter for one metric's live value —
    touching ``._value`` is the accepted, narrow idiom for this (matches
    ``app.dispatcher.metrics.read_gauge``).
    """
    return float(gauge._value.get())
