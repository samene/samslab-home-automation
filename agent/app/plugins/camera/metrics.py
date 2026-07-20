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
CAMERA_SNAPSHOTS_TOTAL = Counter(
    "camera_snapshots_total", "Total camera.snapshot commands that captured and uploaded successfully"
)
CAMERA_SNAPSHOT_DURATION_SECONDS = Histogram(
    "camera_snapshot_duration_seconds", "Time spent capturing and encoding a snapshot, excluding upload"
)
CAMERA_SNAPSHOT_UPLOAD_DURATION_SECONDS = Histogram(
    "camera_snapshot_upload_duration_seconds", "Time spent uploading both snapshot images to S3"
)
CAMERA_SNAPSHOT_FAILURES_TOTAL = Counter(
    "camera_snapshot_failures_total", "Total camera.snapshot commands that failed to capture or upload"
)
CAMERA_RECORDING_ACTIVE = Gauge(
    "camera_recording_active", "Whether local MP4 recording is currently active (0/1)"
)
CAMERA_RECORDINGS_TOTAL = Counter(
    "camera_recordings_total",
    "Total camera.record.stop commands that finalized and uploaded a recording successfully",
)
CAMERA_RECORD_DURATION_SECONDS = Histogram(
    "camera_record_duration_seconds", "Duration of completed camera recordings"
)
CAMERA_RECORD_UPLOAD_DURATION_SECONDS = Histogram(
    "camera_record_upload_duration_seconds", "Time spent uploading a finalized recording to S3"
)
CAMERA_RECORD_FAILURES_TOTAL = Counter(
    "camera_record_failures_total", "Total camera.record.start/stop commands that failed"
)
