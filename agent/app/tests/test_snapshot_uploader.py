"""Tests for S3SnapshotUploader: key naming, upload+verify, and the
build_s3_snapshot_uploader "disabled when unconfigured" factory.

Uses a hand-rolled fake S3 client (matching this codebase's established
fake-over-mocking-library style) rather than a real boto3 client or a
library like moto — no real network call to AWS ever happens here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.plugins.camera.snapshot_uploader import S3SnapshotUploader, build_s3_snapshot_uploader
from app.tests.conftest import make_settings

_CAPTURED_AT = datetime(2026, 3, 5, 12, 0, 0, tzinfo=UTC)


class FakeS3Client:
    """Records put_object/head_object calls against an in-memory object store."""

    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.head_calls: list[dict[str, Any]] = []
        self._objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        self._objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"abc123"'}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.head_calls.append(kwargs)
        key = kwargs["Key"]
        if key not in self._objects:
            raise RuntimeError(f"NoSuchKey: {key}")
        return {"ContentLength": len(self._objects[key])}


def _uploader(client: FakeS3Client, *, prefix: str = "snapshots") -> S3SnapshotUploader:
    return S3SnapshotUploader(client=client, bucket="test-bucket", prefix=prefix)


def test_upload_builds_keys_matching_the_spec_layout() -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        original_bytes=b"original",
        thumbnail_bytes=b"thumb",
        device_name="backyard-pi",
        captured_at=_CAPTURED_AT,
    )

    assert (
        result.original_object_key
        == f"snapshots/2026/03/05/backyard-pi/original/{result.filename}"
    )
    assert (
        result.thumbnail_object_key
        == f"snapshots/2026/03/05/backyard-pi/thumbnails/{result.filename}"
    )
    assert result.bucket == "test-bucket"
    assert result.size == len(b"original")


def test_upload_uses_the_same_filename_for_both_original_and_thumbnail() -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        original_bytes=b"x", thumbnail_bytes=b"y", device_name="d", captured_at=_CAPTURED_AT
    )

    original_name = result.original_object_key.rsplit("/", 1)[-1]
    thumbnail_name = result.thumbnail_object_key.rsplit("/", 1)[-1]
    assert original_name == thumbnail_name == result.filename


def test_upload_verifies_both_objects_via_head_object() -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    uploader.upload(
        original_bytes=b"x", thumbnail_bytes=b"y", device_name="d", captured_at=_CAPTURED_AT
    )

    assert len(client.put_calls) == 2
    assert len(client.head_calls) == 2


def test_upload_returns_the_original_etag_stripped_of_quotes() -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        original_bytes=b"x", thumbnail_bytes=b"y", device_name="d", captured_at=_CAPTURED_AT
    )

    assert result.etag == "abc123"


def test_upload_raises_when_verification_finds_the_object_missing() -> None:
    """A put_object that "succeeds" without actually persisting must still fail loudly."""
    client = FakeS3Client()
    client.put_object = lambda **kwargs: client.put_calls.append(kwargs) or {"ETag": '"abc123"'}  # type: ignore[method-assign,func-returns-value]
    uploader = _uploader(client)

    with pytest.raises(RuntimeError, match="NoSuchKey"):
        uploader.upload(
            original_bytes=b"x", thumbnail_bytes=b"y", device_name="d", captured_at=_CAPTURED_AT
        )


def test_upload_strips_leading_and_trailing_slashes_from_the_prefix() -> None:
    client = FakeS3Client()
    uploader = _uploader(client, prefix="/snapshots/")

    result = uploader.upload(
        original_bytes=b"x", thumbnail_bytes=b"y", device_name="d", captured_at=_CAPTURED_AT
    )

    assert result.original_object_key.startswith("snapshots/2026/03/05/d/original/")


def test_build_s3_snapshot_uploader_returns_none_when_unconfigured() -> None:
    settings = make_settings()
    assert build_s3_snapshot_uploader(settings) is None


def test_build_s3_snapshot_uploader_returns_none_when_only_partially_configured() -> None:
    settings = make_settings(AWS_S3_BUCKET="my-bucket")  # no access key
    assert build_s3_snapshot_uploader(settings) is None


def test_build_s3_snapshot_uploader_returns_an_uploader_when_configured() -> None:
    settings = make_settings(
        AWS_S3_BUCKET="my-bucket",
        AWS_ACCESS_KEY_ID="key",
        AWS_SECRET_ACCESS_KEY="secret",
        AWS_REGION="us-east-1",
    )

    uploader = build_s3_snapshot_uploader(settings)

    assert uploader is not None
