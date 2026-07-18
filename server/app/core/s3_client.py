"""Reads-side Amazon S3 adapter: presigned URLs and object deletion.

Only ``SnapshotApplicationService`` ever depends on this — the only place a
snapshot's *bytes* are read (or removed) from S3. ``CameraApplicationService``
never touches this module; it only persists metadata via ``SnapshotService``.

Deliberately the mirror image of the agent's ``snapshot_uploader.py``: this
side never uploads, and uses separate, least-privilege credentials
(``GetObject``/presign + ``DeleteObject`` only, no ``PutObject``).

``boto3``/``botocore`` are imported lazily inside ``build_s3_client`` rather
than at module scope, matching ``mediamtx_jwt.py``'s "optional adapter"
pattern — importing this module must never require ``boto3`` to be installed
just to run the rest of the server, which doesn't need it at all until a
snapshot-related route is actually hit.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.config.settings import Settings


class S3ClientProtocol(Protocol):
    """The small slice of boto3's S3 client this module actually calls."""

    def generate_presigned_url(
        self, client_method: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str: ...

    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...


class S3Client:
    """Generates presigned GET URLs and deletes objects for one S3 bucket."""

    def __init__(self, *, client: S3ClientProtocol, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def generate_presigned_url(self, object_key: str, *, ttl_seconds: float) -> str:
        """Mint a short-lived, read-only URL for one object — a local HMAC signing operation.

        No network call — safe to call directly from an async route handler.
        """
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=int(ttl_seconds),
        )

    def delete_object(self, object_key: str) -> None:
        """Delete one object. A real network call — callers must run this in an executor."""
        self._client.delete_object(Bucket=self._bucket, Key=object_key)


def build_s3_client(settings: Settings) -> S3Client | None:
    """Build the client from settings, or ``None`` when S3 access isn't configured.

    A missing bucket/credentials is not a startup error — the server still
    starts fine either way; only snapshot routes that need S3 (list/get/delete)
    fail clearly once actually called. Mirrors
    ``build_mediamtx_jwt_signer``'s "``None`` disables the adapter" pattern.
    """
    if settings.aws_s3_bucket is None or settings.aws_access_key_id is None:
        return None

    import boto3

    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        # Pinned explicitly rather than left to botocore's default endpoint
        # resolution: a presigned URL is handed to an external client (the
        # browser) that has no way to follow up a redirect with a re-signed
        # request the way botocore's own request-sending code transparently
        # does for calls we make ourselves (e.g. delete_object). If botocore
        # signs for the region-specific host but resolves a different
        # default (or vice versa), the Host actually used no longer matches
        # what was signed, and S3 rejects the mismatch as SignatureDoesNotMatch
        # — this bit us specifically for eu-central-1, which (unlike
        # us-east-1) has no working legacy global endpoint to fall back to.
        endpoint_url=(
            f"https://s3.{settings.aws_region}.amazonaws.com" if settings.aws_region else None
        ),
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=(
            settings.aws_secret_access_key.get_secret_value()
            if settings.aws_secret_access_key is not None
            else None
        ),
    )
    return S3Client(client=client, bucket=settings.aws_s3_bucket)
