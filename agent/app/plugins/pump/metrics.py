"""Process-global Prometheus metrics for the pump plugin.

Same rationale and pattern as ``app/plugins/camera/metrics.py``: module-level
``Counter``/``Histogram`` objects, defined once at import time.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

PUMP_TRIGGER_TOTAL = Counter(
    "pump_trigger_total", "Total pump.trigger commands that completed a pulse successfully"
)
PUMP_TRIGGER_FAILURES_TOTAL = Counter(
    "pump_trigger_failures_total",
    "Total pump.trigger commands that failed, including rejected concurrent triggers",
)
PUMP_TRIGGER_DURATION_SECONDS = Histogram(
    "pump_trigger_duration_seconds",
    "Wall-clock time spent energizing the pump relay's trigger line",
)
