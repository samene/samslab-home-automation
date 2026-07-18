"""Tests for S3Client: presigned URL generation, object deletion, and settings wiring."""

from __future__ import annotations

from typing import Any

import pytest

from app.config.settings import Settings
from app.core.s3_client import S3Client, S3ClientProtocol, build_s3_client


class FakeS3Client:
    """A hand-rolled double for the small slice of boto3's S3 client S3Client calls."""

    def __init__(self, *, presigned_url: str = "https://s3.example/signed") -> None:
        self.presigned_url = presigned_url
        self.presign_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def generate_presigned_url(
        self, client_method: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        self.presign_calls.append(
            {"client_method": client_method, "Params": Params, "ExpiresIn": ExpiresIn}
        )
        return self.presigned_url

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.delete_calls.append(kwargs)
        return {}


def test_fake_client_satisfies_the_protocol() -> None:
    """The hand-rolled fake matches S3ClientProtocol's shape, same as production boto3."""
    fake: S3ClientProtocol = FakeS3Client()
    assert fake is not None


def test_generate_presigned_url_signs_a_get_object_request_for_the_bucket() -> None:
    """generate_presigned_url mints a GET URL scoped to this client's bucket and object key."""
    fake = FakeS3Client()
    client = S3Client(client=fake, bucket="samslab-snapshots")

    url = client.generate_presigned_url("originals/snapshot.jpg", ttl_seconds=300.0)

    assert url == fake.presigned_url
    assert fake.presign_calls == [
        {
            "client_method": "get_object",
            "Params": {"Bucket": "samslab-snapshots", "Key": "originals/snapshot.jpg"},
            "ExpiresIn": 300,
        }
    ]


def test_generate_presigned_url_truncates_a_fractional_ttl_to_whole_seconds() -> None:
    """ExpiresIn must be an int; a fractional ttl_seconds is truncated, not rejected."""
    fake = FakeS3Client()
    client = S3Client(client=fake, bucket="bucket")

    client.generate_presigned_url("key", ttl_seconds=59.9)

    assert fake.presign_calls[0]["ExpiresIn"] == 59


def test_delete_object_calls_the_client_with_bucket_and_key() -> None:
    """delete_object issues a real Bucket/Key delete call scoped to this client's bucket."""
    fake = FakeS3Client()
    client = S3Client(client=fake, bucket="samslab-snapshots")

    client.delete_object("thumbnails/snapshot.jpg")

    assert fake.delete_calls == [{"Bucket": "samslab-snapshots", "Key": "thumbnails/snapshot.jpg"}]


def test_delete_object_propagates_client_errors() -> None:
    """A failing delete call is not swallowed here — that's the application service's job."""

    class _FailingClient(FakeS3Client):
        def delete_object(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("network error")

    client = S3Client(client=_FailingClient(), bucket="bucket")

    with pytest.raises(RuntimeError, match="network error"):
        client.delete_object("key")


def test_build_s3_client_returns_none_when_bucket_unset() -> None:
    """No bucket configured means S3 access stays disabled, not a startup error."""
    settings = Settings(
        ENVIRONMENT="test",
        AWS_ACCESS_KEY_ID="AKIAEXAMPLE",
        AWS_SECRET_ACCESS_KEY="secret",
    )
    assert build_s3_client(settings) is None


def test_build_s3_client_returns_none_when_access_key_unset() -> None:
    """No access key configured also disables the adapter, independent of the bucket."""
    settings = Settings(ENVIRONMENT="test", AWS_S3_BUCKET="samslab-snapshots")
    assert build_s3_client(settings) is None


def test_build_s3_client_returns_none_when_nothing_is_configured() -> None:
    """The common case — no AWS settings at all — must not raise or require boto3 to connect."""
    settings = Settings(ENVIRONMENT="test")
    assert build_s3_client(settings) is None


def test_build_s3_client_builds_a_working_client_from_settings() -> None:
    """A fully configured environment yields a real S3Client that can sign locally."""
    settings = Settings(
        ENVIRONMENT="test",
        AWS_REGION="us-east-1",
        AWS_ACCESS_KEY_ID="AKIAEXAMPLE",
        AWS_SECRET_ACCESS_KEY="secret",
        AWS_S3_BUCKET="samslab-snapshots",
    )

    client = build_s3_client(settings)

    assert client is not None
    assert isinstance(client, S3Client)
    url = client.generate_presigned_url("originals/snapshot.jpg", ttl_seconds=300.0)
    assert url.startswith("https://")
    assert "samslab-snapshots" in url
