"""Tests for S3RecordingUploader: key naming, video+thumbnail upload+verify,
and the build_s3_recording_uploader "disabled when unconfigured" factory.

Uses a hand-rolled fake S3 client (matching test_snapshot_uploader.py's
established fake-over-mocking-library style) rather than a real boto3 client
or a library like moto — no real network call to AWS ever happens here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.plugins.camera.recording_uploader import S3RecordingUploader, build_s3_recording_uploader
from app.tests.conftest import make_settings

_RECORDED_AT = datetime(2026, 3, 5, 12, 0, 0, tzinfo=UTC)


class FakeS3Client:
    """Records upload_file/put_object/head_object calls against an in-memory object store."""

    def __init__(self) -> None:
        self.upload_file_calls: list[dict[str, Any]] = []
        self.put_calls: list[dict[str, Any]] = []
        self.head_calls: list[dict[str, Any]] = []
        self._objects: set[str] = set()

    def upload_file(
        self, Filename: str, Bucket: str, Key: str, ExtraArgs: dict[str, Any] | None = None
    ) -> None:
        self.upload_file_calls.append(
            {"Filename": Filename, "Bucket": Bucket, "Key": Key, "ExtraArgs": ExtraArgs}
        )
        self._objects.add(Key)

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        self._objects.add(kwargs["Key"])
        return {"ETag": '"abc123"'}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.head_calls.append(kwargs)
        key = kwargs["Key"]
        if key not in self._objects:
            raise RuntimeError(f"NoSuchKey: {key}")
        return {"ETag": '"abc123"'}


def _uploader(client: FakeS3Client) -> S3RecordingUploader:
    return S3RecordingUploader(client=client, bucket="test-bucket")


def _write_temp_video(tmp_path: Path) -> Path:
    path = tmp_path / "recording.mp4"
    path.write_bytes(b"fake-mp4-bytes")
    return path


def test_upload_builds_a_key_under_the_fixed_videos_prefix(tmp_path: Path) -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        file_path=_write_temp_video(tmp_path), device_name="backyard-pi", recorded_at=_RECORDED_AT
    )

    assert result.object_key == f"videos/2026/03/05/backyard-pi/{result.filename}"
    assert result.filename.endswith(".mp4")
    assert result.bucket == "test-bucket"
    assert result.size == len(b"fake-mp4-bytes")


def test_upload_verifies_the_video_via_head_object(tmp_path: Path) -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    uploader.upload(
        file_path=_write_temp_video(tmp_path), device_name="d", recorded_at=_RECORDED_AT
    )

    assert len(client.upload_file_calls) == 1
    assert len(client.head_calls) == 1
    assert client.upload_file_calls[0]["ExtraArgs"] == {"ContentType": "video/mp4"}


def test_upload_returns_the_etag_stripped_of_quotes(tmp_path: Path) -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        file_path=_write_temp_video(tmp_path), device_name="d", recorded_at=_RECORDED_AT
    )

    assert result.etag == "abc123"


def test_upload_omits_the_thumbnail_when_none_is_given(tmp_path: Path) -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        file_path=_write_temp_video(tmp_path), device_name="d", recorded_at=_RECORDED_AT
    )

    assert result.thumbnail_object_key is None
    assert len(client.put_calls) == 0


def test_upload_uploads_a_thumbnail_alongside_the_video_when_given(tmp_path: Path) -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    result = uploader.upload(
        file_path=_write_temp_video(tmp_path),
        device_name="backyard-pi",
        recorded_at=_RECORDED_AT,
        thumbnail_bytes=b"fake-jpeg-bytes",
    )

    assert result.thumbnail_object_key is not None
    assert result.thumbnail_object_key.startswith("videos/2026/03/05/backyard-pi/thumbnails/")
    assert result.thumbnail_object_key.endswith(".jpg")
    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Body"] == b"fake-jpeg-bytes"
    assert client.put_calls[0]["ContentType"] == "image/jpeg"
    # The video and thumbnail keys share the same uuid stem, like snapshots do.
    video_stem = result.object_key.rsplit("/", 1)[-1].removesuffix(".mp4")
    thumbnail_stem = result.thumbnail_object_key.rsplit("/", 1)[-1].removesuffix(".jpg")
    assert video_stem == thumbnail_stem


def test_upload_verifies_the_thumbnail_via_head_object_too(tmp_path: Path) -> None:
    client = FakeS3Client()
    uploader = _uploader(client)

    uploader.upload(
        file_path=_write_temp_video(tmp_path),
        device_name="d",
        recorded_at=_RECORDED_AT,
        thumbnail_bytes=b"fake-jpeg-bytes",
    )

    assert len(client.head_calls) == 2


def test_upload_raises_when_thumbnail_verification_finds_it_missing(tmp_path: Path) -> None:
    client = FakeS3Client()
    client.put_object = lambda **kwargs: client.put_calls.append(kwargs) or {"ETag": '"abc123"'}  # type: ignore[method-assign,func-returns-value]
    uploader = _uploader(client)

    with pytest.raises(RuntimeError, match="NoSuchKey"):
        uploader.upload(
            file_path=_write_temp_video(tmp_path),
            device_name="d",
            recorded_at=_RECORDED_AT,
            thumbnail_bytes=b"fake-jpeg-bytes",
        )


def test_build_s3_recording_uploader_returns_none_when_unconfigured() -> None:
    settings = make_settings()
    assert build_s3_recording_uploader(settings) is None


def test_build_s3_recording_uploader_returns_none_when_only_partially_configured() -> None:
    settings = make_settings(AWS_S3_BUCKET="my-bucket")  # no access key
    assert build_s3_recording_uploader(settings) is None


def test_build_s3_recording_uploader_returns_an_uploader_when_configured() -> None:
    settings = make_settings(
        AWS_S3_BUCKET="my-bucket",
        AWS_ACCESS_KEY_ID="key",
        AWS_SECRET_ACCESS_KEY="secret",
        AWS_REGION="us-east-1",
    )

    uploader = build_s3_recording_uploader(settings)

    assert uploader is not None
