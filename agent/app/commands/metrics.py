"""Process-global Prometheus metrics for the command runtime.

Same deliberate, narrow exception to "no module-level singletons" as
``app/metrics/registry.py`` — these are conventionally process-global and
defined once at import time.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

COMMANDS_RECEIVED_TOTAL = Counter(
    "commands_received_total", "Total COMMAND messages received", ["command_type"]
)
COMMANDS_COMPLETED_TOTAL = Counter(
    "commands_completed_total", "Total commands completed successfully", ["command_type"]
)
COMMANDS_FAILED_TOTAL = Counter(
    "commands_failed_total", "Total commands that failed", ["command_type"]
)
COMMANDS_TIMEOUT_TOTAL = Counter(
    "commands_timeout_total", "Total commands that timed out", ["command_type"]
)
COMMAND_EXECUTION_DURATION_SECONDS = Histogram(
    "command_execution_duration_seconds",
    "Command execution duration in seconds",
    ["command_type"],
)
REGISTERED_HANDLERS = Gauge(
    "registered_handlers", "Number of currently registered command handlers"
)
RUNNING_COMMANDS = Gauge("running_commands", "Number of commands currently executing")
