"""Process-global Prometheus metrics for the terminal plugin.

Same rationale and pattern as ``app/metrics/registry.py``/``camera/metrics.py``:
module-level ``Counter``/``Gauge`` objects, defined once at import time.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

TERMINAL_SESSIONS_ACTIVE = Gauge(
    "terminal_sessions_active", "Number of currently open interactive PTY sessions"
)
TERMINAL_SESSIONS_OPENED_TOTAL = Counter(
    "terminal_sessions_opened_total", "Total interactive terminal sessions successfully opened"
)
TERMINAL_SESSIONS_CLOSED_TOTAL = Counter(
    "terminal_sessions_closed_total", "Total interactive terminal sessions closed, any reason"
)
TERMINAL_SESSION_ERRORS_TOTAL = Counter(
    "terminal_session_errors_total", "Total terminal session errors (spawn failure, disabled, etc.)"
)
