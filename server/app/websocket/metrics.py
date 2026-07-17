"""Process-global Prometheus metrics for the WebSocket gateway.

Module-level ``Counter``/``Gauge``/``Histogram`` objects are the idiomatic
``prometheus_client`` pattern and a deliberate, narrow exception to this
codebase's "no module-level singletons" rule: metrics are conventionally
process-global, defined once at import time, and safe to share across every
``create_app()`` instance built in the same process (e.g. one per test).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

CONNECTED_DEVICES = Gauge("connected_devices", "Number of devices with an open WebSocket session")
ACTIVE_SESSIONS = Gauge("active_sessions", "Number of active WebSocket gateway sessions")
MESSAGES_SENT_TOTAL = Counter(
    "messages_sent_total", "Total messages sent to agents", ["message_type"]
)
MESSAGES_RECEIVED_TOTAL = Counter(
    "messages_received_total", "Total messages received from agents", ["message_type"]
)
BYTES_SENT_TOTAL = Counter("bytes_sent_total", "Total bytes sent to agents")
BYTES_RECEIVED_TOTAL = Counter("bytes_received_total", "Total bytes received from agents")
AUTHENTICATION_FAILURES_TOTAL = Counter(
    "authentication_failures_total", "Total WebSocket handshake authentication failures"
)
HEARTBEAT_FAILURES_TOTAL = Counter(
    "heartbeat_failures_total", "Total heartbeat or idle timeouts that closed a connection"
)
CONNECTION_DURATION = Histogram(
    "connection_duration", "Duration of completed WebSocket connections, in seconds"
)
