"""Process-global Prometheus metrics for the camera plugin.

Same rationale and pattern as ``app/metrics/registry.py``: module-level
``Counter``/``Gauge``/``Histogram`` objects, defined once at import time.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

CAMERA_STREAM_ACTIVE = Gauge(
    "camera_stream_active", "Whether the live camera stream is currently active (0/1)"
)
CAMERA_STREAM_DURATION_SECONDS = Histogram(
    "camera_stream_duration_seconds", "Duration of completed camera streaming sessions"
)
CAMERA_STREAM_START_TOTAL = Counter(
    "camera_stream_start_total", "Total camera.stream.start commands that began streaming"
)
CAMERA_STREAM_STOP_TOTAL = Counter(
    "camera_stream_stop_total", "Total camera.stream.stop commands that stopped streaming"
)
CAMERA_FRAMES_SENT_TOTAL = Counter(
    "camera_frames_sent_total", "Total video frames published to MediaMTX"
)
CAMERA_STREAM_ERRORS_TOTAL = Counter(
    "camera_stream_errors_total", "Total camera/publisher errors while starting or streaming"
)
