"""Process-global Prometheus metrics for the Command Dispatcher.

Module-level ``Counter``/``Gauge``/``Histogram`` objects, the same deliberate,
narrow exception to "no module-level singletons" already established in
``app.websocket.metrics`` — metrics are conventionally process-global and
defined once at import time, safe to share across every ``create_app()``
instance in one process (e.g. one per test).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

COMMANDS_DISPATCHED_TOTAL = Counter(
    "commands_dispatched_total", "Total commands successfully handed to a connected device"
)
DISPATCH_FAILURES_TOTAL = Counter(
    "dispatch_failures_total", "Total dispatch attempts that failed at the transport level"
)
COMMAND_ACK_LATENCY_SECONDS = Histogram(
    "command_ack_latency_seconds", "Time from dispatch to a device's COMMAND_ACK"
)
COMMAND_EXECUTION_SECONDS = Histogram(
    "command_execution_seconds", "Time from RUNNING to a terminal COMMAND_RESULT"
)
DISPATCHER_QUEUE_DEPTH = Gauge(
    "dispatcher_queue_depth", "Number of commands currently queued for dispatch"
)
DISPATCHER_RETRIES_TOTAL = Counter(
    "dispatcher_retries_total", "Total redelivery attempts after an acknowledgement timeout"
)
DISPATCHER_TIMEOUTS_TOTAL = Counter(
    "dispatcher_timeouts_total", "Total commands transitioned to TIMEOUT by the dispatcher"
)
PENDING_COMMANDS = Gauge(
    "pending_commands", "Number of commands awaiting dispatch (PENDING/QUEUED)"
)
RUNNING_COMMANDS = Gauge("running_commands", "Number of commands currently RUNNING on a device")


def read_counter(counter: Counter) -> float:
    """Read a Counter's current value for the read-only statistics endpoint.

    ``prometheus_client`` has no public getter for one metric's live value —
    ``generate_latest()`` is for full scrape exposition, not a single read.
    Touching ``._value`` is the accepted, narrow idiom for this.
    """
    return float(counter._value.get())


def read_gauge(gauge: Gauge) -> float:
    """Read a Gauge's current value for the read-only statistics endpoint."""
    return float(gauge._value.get())
