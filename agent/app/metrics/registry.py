"""Process-global Prometheus metrics for the agent.

Module-level ``Counter``/``Gauge`` objects are the idiomatic ``prometheus_client``
pattern and a deliberate, narrow exception to the "no module-level singletons"
rule applied elsewhere in this codebase: metrics are conventionally
process-global, defined once at import time. Any test asserting on a metric
value must use a before/after delta, since counters accumulate for the life of
the process (or the whole pytest session, if tests share one process).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

AGENT_UPTIME_SECONDS = Gauge("agent_uptime_seconds", "Seconds since the agent process started")
AGENT_CONNECTED = Gauge(
    "agent_connected", "Whether the agent currently has an open connection (0/1)"
)
CONNECTION_ATTEMPTS_TOTAL = Counter(
    "connection_attempts_total", "Total connection attempts made to the server"
)
HEARTBEAT_TOTAL = Counter("heartbeat_total", "Total heartbeats sent to the server")
HEARTBEAT_FAILURES_TOTAL = Counter("heartbeat_failures_total", "Total heartbeats that failed")
RECONNECT_TOTAL = Counter("reconnect_total", "Total reconnect attempts after a lost connection")
MESSAGES_SENT_TOTAL = Counter(
    "messages_sent_total", "Total protocol messages sent to the server", ["message_type"]
)
MESSAGES_RECEIVED_TOTAL = Counter(
    "messages_received_total", "Total protocol messages received from the server", ["message_type"]
)
DEVICE_TOKEN_REQUESTS_TOTAL = Counter(
    "device_token_requests_total",
    "Total device access-token requests (signed-assertion exchanges)",
)
DEVICE_TOKEN_REQUEST_FAILURES_TOTAL = Counter(
    "device_token_request_failures_total", "Total device access-token requests that failed"
)
