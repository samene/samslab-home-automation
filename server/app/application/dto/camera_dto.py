"""Camera stream lifecycle data transfer objects.

There is no Camera domain or persisted model — these DTOs are shaped entirely
by the ``camera.stream.start``/``camera.stream.stop`` command results and by
server-side MediaMTX configuration (see ``CameraApplicationService``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CameraStatusDTO(BaseModel):
    """Current camera stream state, returned by both start and status endpoints."""

    running: bool
    stream_name: str
    playback_url: str
    # A short-lived MediaMTX read JWT (see app/core/mediamtx_jwt.py), minted
    # fresh on every response — never persisted, always attached by the
    # frontend as an Authorization: Bearer header via hls.js. None when
    # MediaMTX JWT auth isn't configured server-side.
    playback_token: str | None = None
    resolution: str | None = None
    fps: int | None = None
    started_at: datetime | None = None
    uptime_seconds: float = 0.0
    # Always 0 today — MediaMTX reader-count polling is a future extension.
    viewer_count: int = 0


class CameraStopDTO(BaseModel):
    """Outcome of a ``camera.stream.stop`` command."""

    status: str
    duration_seconds: float | None = None
    frames_sent: int | None = None
    stopped_at: datetime | None = None
