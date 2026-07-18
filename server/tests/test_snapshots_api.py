"""REST API tests for the Snapshot Gallery (GET/GET-by-id/DELETE), mirroring test_devices.py.

There is no POST /snapshots — snapshots are only ever created by a completed
camera.snapshot command (see CameraApplicationService.capture_snapshot), so every
test here seeds a Snapshot row directly through SnapshotService in a setup step,
committing before making any HTTP call against a *different* session (see
CLAUDE.md's "Testing pattern" section for why the commit must happen explicitly).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.commands.models import Command
from app.domains.commands.repository import CommandRepository
from app.domains.devices.models import Device
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService
from app.domains.snapshots.models import Snapshot
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService
from app.main import create_app


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'snapshots_api.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def _app_for(database: Database) -> FastAPI:
    """Build an app wired to a real S3 adapter so presigned URLs are real, signed URLs."""
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            AWS_REGION="us-east-1",
            AWS_ACCESS_KEY_ID="AKIAEXAMPLE",
            AWS_SECRET_ACCESS_KEY="secret",
            AWS_S3_BUCKET="samslab-snapshots",
            AWS_PRESIGNED_URL_TTL_SECONDS=120.0,
        )
    )
    app.state.container.database.override(database)
    return app


async def _seed_device(database: Database) -> Device:
    async with database.session_factory() as session:
        device = await DeviceService(DeviceRepository(session)).register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "garden-pi",
                    "hostname": "garden-pi.local",
                    "display_name": "Garden Pi",
                }
            )
        )
        await session.commit()
        return device


async def _seed_snapshot(database: Database, device_id: UUID, **overrides: Any) -> Snapshot:
    """Seed one snapshot (plus the command row its FK requires) and commit it.

    Commits explicitly, in its own session, so the HTTP client's request — which
    runs through a *different* session opened per-request by the API — sees it.
    """
    async with database.session_factory() as session:
        command = await CommandRepository(session).create(
            Command(device_id=device_id, command_type="camera.snapshot", payload={})
        )
        values: dict[str, Any] = {
            "device_id": device_id,
            "command_id": command.id,
            "filename": "snapshot.jpg",
            "bucket": "samslab-snapshots",
            "original_object_key": "originals/snapshot.jpg",
            "thumbnail_object_key": "thumbnails/snapshot.jpg",
            "etag": '"abc123"',
            "sha256": "a" * 64,
            "width": 1920,
            "height": 1080,
            "size": 204800,
            "captured_at": datetime.now(UTC),
        }
        values.update(overrides)
        snapshot = await SnapshotService(SnapshotRepository(session)).record_snapshot(**values)
        await session.commit()
        return snapshot


@pytest.mark.asyncio
async def test_api_lists_empty_when_no_snapshots_exist(database: Database) -> None:
    """A fresh database has no snapshots at all, and the page shape stays consistent."""
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/snapshots")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_api_lists_snapshots_with_real_presigned_urls(database: Database) -> None:
    """Listed snapshots carry freshly minted presigned URLs, never raw object keys."""
    device = await _seed_device(database)
    await _seed_snapshot(database, device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/snapshots")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["thumbnail_url"].startswith("https://")
    assert item["image_url"].startswith("https://")
    assert item["thumbnail_url"] != "thumbnails/snapshot.jpg"
    assert item["image_url"] != "originals/snapshot.jpg"


@pytest.mark.asyncio
async def test_api_lists_snapshots_scoped_to_one_device(database: Database) -> None:
    """The device_id filter excludes snapshots captured by any other device."""
    device = await _seed_device(database)
    async with database.session_factory() as session:
        other_device = await DeviceService(DeviceRepository(session)).register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "other-pi",
                    "hostname": "other-pi.local",
                    "display_name": "Other Pi",
                }
            )
        )
        await session.commit()
    await _seed_snapshot(database, device.id)
    await _seed_snapshot(database, other_device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/snapshots", params={"device_id": str(device.id)})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["device_id"] == str(device.id)


@pytest.mark.asyncio
async def test_api_gets_one_snapshot_by_id(database: Database) -> None:
    device = await _seed_device(database)
    snapshot = await _seed_snapshot(database, device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/snapshots/{snapshot.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(snapshot.id)
    assert body["filename"] == "snapshot.jpg"
    assert body["thumbnail_url"].startswith("https://")


@pytest.mark.asyncio
async def test_api_get_missing_snapshot_returns_404_problem_json(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/snapshots/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_api_deletes_a_snapshot_then_get_returns_404(database: Database) -> None:
    device = await _seed_device(database)
    snapshot = await _seed_snapshot(database, device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        deleted = await client.delete(f"/snapshots/{snapshot.id}")
        assert deleted.status_code == 204

        missing = await client.get(f"/snapshots/{snapshot.id}")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_api_delete_missing_snapshot_returns_404_problem_json(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(f"/snapshots/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_api_returns_503_without_configured_database() -> None:
    """The Snapshots endpoints fail safely when no database is configured."""
    app: FastAPI = create_app(Settings(ENVIRONMENT=Environment.TEST))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/snapshots")
    assert response.status_code == 503
