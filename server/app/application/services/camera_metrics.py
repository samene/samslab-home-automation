"""Process-global Prometheus metrics for camera recording.

Module-level ``Counter``/``Histogram`` objects, the same deliberate, narrow
exception to "no module-level singletons" already established in
``app.websocket.metrics``/``app.dispatcher.metrics``/``app.scheduler.metrics``
— metrics are conventionally process-global, defined once at import time, and
safe to share across every ``create_app()`` instance built in the same
process (e.g. one per test).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

CAMERA_RECORDINGS_TOTAL = Counter(
    "camera_recordings_total", "Total recordings successfully finalized and uploaded to S3"
)
CAMERA_RECORD_DURATION_SECONDS = Histogram(
    "camera_record_duration_seconds", "Length of the recorded video itself, start to stop"
)
CAMERA_RECORD_UPLOAD_DURATION_SECONDS = Histogram(
    "camera_record_upload_duration_seconds", "Time spent uploading the finished MP4 to S3"
)
CAMERA_RECORD_FAILURES_TOTAL = Counter(
    "camera_record_failures_total", "Total camera.record.start/stop commands that did not complete"
)
