"""Uploads finalized MP4 recordings directly to Amazon S3, independent of streaming.

``CameraService.stop_recording()`` calls into this module only after the
local MP4 is fully finalized; nothing here ever touches camera hardware or
ffmpeg — this is purely the "upload one file, verify, report back the object
key" seam, injected into ``CameraService`` the same way
``frame_source_factory``/``publisher_factory``/``uploader`` already are, so
tests can supply a hand-rolled fake instead of a real network-calling boto3
client.

Uses the S3 client's ``upload_file`` (not ``put_object``, unlike
``snapshot_uploader.py``) — a finished recording can be many hundreds of
megabytes to gigabytes, and ``put_object`` would require buffering the whole
file in memory first. ``upload_file`` streams it from disk instead.
``boto3``/``botocore`` are imported lazily, matching ``snapshot_uploader.py``'s
and ``sources.py``'s pattern — importing this module must never require the
``camera`` extra's ``boto3`` dependency just to use streaming, which doesn't
need it at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.config.settings import AgentSettings

#: Recordings live under a fixed, agent-decided top-level prefix, a sibling
#: tree to snapshots' own ``<AWS_S3_PREFIX>``-relative keys — not relative to
#: ``aws_s3_prefix`` itself, which is a snapshot-path-only setting.
_PREFIX = "videos"


class S3RecordingClientProtocol(Protocol):
    """The small slice of boto3's S3 client this module actually calls."""

    def upload_file(
        self, Filename: str, Bucket: str, Key: str, ExtraArgs: dict[str, Any] | None = None
    ) -> None: ...

    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...


class RecordingUploaderProtocol(Protocol):
    """The shape ``CameraService`` depends on — matches ``S3RecordingUploader.upload``.

    A ``Protocol``, not the concrete ``S3RecordingUploader`` class, so a
    hand-rolled test fake is structurally accepted by ``CameraService``'s
    constructor, matching the existing ``FrameSource``/``StreamPublisher``/
    ``SnapshotUploaderProtocol`` injection pattern.
    """

    def upload(
        self,
        *,
        file_path: Path,
        device_name: str,
        recorded_at: datetime,
        thumbnail_bytes: bytes | None = None,
    ) -> RecordingUploadResult: ...


@dataclass(frozen=True, slots=True)
class RecordingUploadResult:
    """Everything ``CameraService.stop_recording()`` needs to report back — no video bytes."""

    bucket: str
    filename: str
    object_key: str
    thumbnail_object_key: str | None
    etag: str | None
    size: int


class S3RecordingUploader:
    """Uploads one finalized MP4 to S3 under ``videos/YYYY/MM/DD/<device-name>/<uuid>.mp4``.

    ``thumbnail_bytes``, when given, is a small JPEG uploaded alongside it
    under a sibling ``thumbnails/`` key with the same ``<uuid>`` stem —
    mirroring ``S3SnapshotUploader``'s original/thumbnail pairing-by-filename
    convention — so the two objects for one recording are trivially paired
    back up from either key alone.
    """

    def __init__(self, *, client: S3RecordingClientProtocol, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def upload(
        self,
        *,
        file_path: Path,
        device_name: str,
        recorded_at: datetime,
        thumbnail_bytes: bytes | None = None,
    ) -> RecordingUploadResult:
        """Upload the file (plus an optional thumbnail), verifying each write; raises on failure."""
        stem = str(uuid4())
        filename = f"{stem}.mp4"
        date_path = recorded_at.strftime("%Y/%m/%d")
        base = f"{_PREFIX}/{date_path}/{device_name}"
        object_key = f"{base}/{filename}"

        self._client.upload_file(
            Filename=str(file_path),
            Bucket=self._bucket,
            Key=object_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        # A real confirming round trip, not just trusting upload_file's own
        # success — matches S3SnapshotUploader's same "catches a bucket
        # policy that silently accepts a write without persisting it" logic,
        # and is also the only way to read back an ETag here, since
        # upload_file's managed multipart transfer doesn't return one directly.
        head = self._client.head_object(Bucket=self._bucket, Key=object_key)
        etag = head.get("ETag")

        thumbnail_object_key: str | None = None
        if thumbnail_bytes is not None:
            thumbnail_object_key = f"{base}/thumbnails/{stem}.jpg"
            self._client.put_object(
                Bucket=self._bucket,
                Key=thumbnail_object_key,
                Body=thumbnail_bytes,
                ContentType="image/jpeg",
            )
            self._client.head_object(Bucket=self._bucket, Key=thumbnail_object_key)

        return RecordingUploadResult(
            bucket=self._bucket,
            filename=filename,
            object_key=object_key,
            thumbnail_object_key=thumbnail_object_key,
            etag=etag.strip('"') if isinstance(etag, str) else None,
            size=file_path.stat().st_size,
        )


def build_s3_recording_uploader(settings: AgentSettings) -> S3RecordingUploader | None:
    """Build the uploader from settings, or ``None`` when S3 upload isn't configured.

    Reuses the exact same ``AWS_*`` credentials as the snapshot uploader (see
    ``build_s3_snapshot_uploader``) — the same least-privilege IAM user, just
    also needing ``PutObject`` under this bucket's ``videos/`` prefix. A
    missing bucket/credentials is not a startup error — only
    ``stop_recording()`` fails (via ``CameraUnavailableError``) if a
    recording is actually stopped with no S3 configured.
    """
    if settings.aws_s3_bucket is None or settings.aws_access_key_id is None:
        return None

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=(
            f"https://s3.{settings.aws_region}.amazonaws.com" if settings.aws_region else None
        ),
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=(
            settings.aws_secret_access_key.get_secret_value()
            if settings.aws_secret_access_key is not None
            else None
        ),
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )
    return S3RecordingUploader(client=client, bucket=settings.aws_s3_bucket)
