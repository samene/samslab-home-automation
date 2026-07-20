"""Process-global Prometheus metrics for the Notification Framework.

Module-level ``Counter``/``Histogram`` objects, the same deliberate, narrow
exception to "no module-level singletons" already established in
``app.dispatcher.metrics``/``app.websocket.metrics`` — metrics are
conventionally process-global, defined once at import time.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

NOTIFICATIONS_SENT_TOTAL = Counter(
    "notifications_sent_total", "Total notifications successfully delivered", ["provider"]
)
NOTIFICATIONS_FAILED_TOTAL = Counter(
    "notifications_failed_total", "Total notifications that failed to deliver", ["provider"]
)
TELEGRAM_NOTIFICATIONS_TOTAL = Counter(
    "telegram_notifications_total", "Total Telegram send attempts, successful or not"
)
TELEGRAM_NOTIFICATION_DURATION_SECONDS = Histogram(
    "telegram_notification_duration_seconds",
    "Time spent sending one Telegram message, including retries",
)
