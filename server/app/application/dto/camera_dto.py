"""Camera stream lifecycle data transfer objects.

There is no Camera domain or persisted model — these DTOs are shaped entirely
by the ``camera.stream.start``/``camera.stream.stop`` command results and by
server-side MediaMTX configuration (see ``CameraApplicationService``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

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


class CameraSnapshotDTO(BaseModel):
    """Outcome of a ``camera.snapshot`` command — metadata only, never image bytes.

    Deliberately has no ``thumbnail_url``/``image_url``: those are minted
    only by ``SavedMediaApplicationService`` (``GET /saved-media``,
    ``GET /saved-media/{id}``), not here — see ``CameraApplicationService``'s
    docstring for why ``capture_snapshot`` never touches S3 for reads.
    """

    id: UUID
    device_id: UUID
    command_id: UUID
    filename: str
    width: int
    height: int
    size: int
    captured_at: datetime


class CameraRecordingStartedDTO(BaseModel):
    """Outcome of a ``camera.record.start`` command — recording is now in progress."""

    status: str
    filename: str
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    started_at: datetime | None = None


class CameraRecordingDTO(BaseModel):
    """Outcome of a ``camera.record.stop`` command — metadata only, never video bytes.

    Deliberately has no ``video_url``: that's minted only by
    ``SavedMediaApplicationService`` (``GET /saved-media/{id}``), not here —
    same reasoning as ``CameraSnapshotDTO``.
    """

    id: UUID
    bucket: str
    object_key: str
    etag: str | None
    sha256: str
    filename: str
    duration_seconds: float
    width: int
    height: int
    fps: int | None
    bitrate: int | None
    file_size: int
    recorded_at: datetime
    upload_duration_seconds: float
