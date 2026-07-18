"""Uploads snapshot images directly to Amazon S3, independent of streaming.

``CameraService.capture_snapshot()`` calls into this module after encoding a
JPEG (and thumbnail); nothing here ever touches camera hardware or knows
about ``FrameSource``/``StreamPublisher`` — this is purely the "upload two
files, verify, report back object keys" seam, injected into ``CameraService``
the same way ``frame_source_factory``/``publisher_factory`` already are, so
tests can supply a hand-rolled fake instead of a real network-calling boto3
client.

``boto3``/``botocore`` are imported lazily inside ``build_s3_snapshot_uploader``
rather than at module scope, matching ``sources.py``'s lazy ``cv2``/``picamera2``
imports — importing this module (e.g. transitively via ``service.py``) must
never require the ``camera`` extra's ``boto3`` dependency to be installed
just to use streaming, which doesn't need it at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from app.config.settings import AgentSettings


class S3ClientProtocol(Protocol):
    """The small slice of boto3's S3 client this module actually calls."""

    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...


class SnapshotUploaderProtocol(Protocol):
    """The shape ``CameraService`` depends on — matches ``S3SnapshotUploader.upload``.

    A ``Protocol``, not the concrete ``S3SnapshotUploader`` class, so a
    hand-rolled test fake (e.g. ``FakeUploader``) is structurally accepted by
    ``CameraService.__init__``'s type hint, matching the existing
    ``FrameSource``/``StreamPublisher`` injection pattern.
    """

    def upload(
        self,
        *,
        original_bytes: bytes,
        thumbnail_bytes: bytes,
        device_name: str,
        captured_at: datetime,
    ) -> SnapshotUploadResult: ...


@dataclass(frozen=True, slots=True)
class SnapshotUploadResult:
    """Everything ``CameraService.capture_snapshot()`` needs to report back — no image bytes."""

    bucket: str
    filename: str
    original_object_key: str
    thumbnail_object_key: str
    etag: str | None
    size: int


class S3SnapshotUploader:
    """Uploads an original+thumbnail JPEG pair to S3 under a date/device-scoped key.

    Keys follow ``<prefix>/YYYY/MM/DD/<device-name>/original|thumbnails/<uuid>.jpg``
    — the same ``<uuid>.jpg`` filename in both, so the two objects for one
    capture are trivially paired back up from either key alone.
    """

    def __init__(self, *, client: S3ClientProtocol, bucket: str, prefix: str) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def upload(
        self,
        *,
        original_bytes: bytes,
        thumbnail_bytes: bytes,
        device_name: str,
        captured_at: datetime,
    ) -> SnapshotUploadResult:
        """Upload both images, verifying each write; raises on any failure."""
        filename = f"{uuid4()}.jpg"
        date_path = captured_at.strftime("%Y/%m/%d")
        base = f"{self._prefix}/{date_path}/{device_name}"
        original_key = f"{base}/original/{filename}"
        thumbnail_key = f"{base}/thumbnails/{filename}"

        original_response = self._put_and_verify(original_key, original_bytes)
        self._put_and_verify(thumbnail_key, thumbnail_bytes)

        etag = original_response.get("ETag")
        return SnapshotUploadResult(
            bucket=self._bucket,
            filename=filename,
            original_object_key=original_key,
            thumbnail_object_key=thumbnail_key,
            etag=etag.strip('"') if isinstance(etag, str) else None,
            size=len(original_bytes),
        )

    def _put_and_verify(self, key: str, body: bytes) -> dict[str, Any]:
        response = self._client.put_object(
            Bucket=self._bucket, Key=key, Body=body, ContentType="image/jpeg"
        )
        # A real confirming round trip, not just trusting put_object's own
        # response — catches a bucket policy that silently accepts a write
        # without actually persisting it. Raises (via the client, e.g.
        # botocore.exceptions.ClientError) if the object isn't really there.
        self._client.head_object(Bucket=self._bucket, Key=key)
        return response


def build_s3_snapshot_uploader(settings: AgentSettings) -> S3SnapshotUploader | None:
    """Build the uploader from settings, or ``None`` when S3 upload isn't configured.

    A missing bucket/credentials is not a startup error — the agent still
    starts and streams fine either way; only ``capture_snapshot()`` fails
    (clearly, via ``CameraUnavailableError``) if a snapshot is actually
    requested with no S3 configured. Mirrors the cloud server's
    ``build_mediamtx_jwt_signer``'s "``None`` disables the adapter" pattern.
    """
    if settings.aws_s3_bucket is None or settings.aws_access_key_id is None:
        return None

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        # Pinned explicitly rather than left to botocore's default endpoint
        # resolution — see the matching comment in server/app/core/s3_client.py,
        # which is where this actually bit us (a presigned GET URL can't
        # benefit from botocore's transparent redirect-and-resign retry the
        # way put_object/head_object calls here do, so relying on default
        # resolution for one side but not the other is asking for exactly
        # this class of region/host mismatch again in the future).
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
    return S3SnapshotUploader(
        client=client, bucket=settings.aws_s3_bucket, prefix=settings.aws_s3_prefix
    )
