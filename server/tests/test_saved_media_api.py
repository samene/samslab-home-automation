"""REST API tests for Saved Media (GET/GET-by-id/DELETE), mirroring test_devices.py.

There is no POST /saved-media — rows are only ever created by a completed
camera.snapshot/camera.record.stop command (see
CameraApplicationService.capture_snapshot/stop_recording), so every test
here seeds a SavedMedia row directly through SavedMediaService in a setup
step, committing before making any HTTP call against a *different* session
(see CLAUDE.md's "Testing pattern" section for why the commit must happen
explicitly).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from app.domains.saved_media.models import MediaType, SavedMedia
from app.domains.saved_media.repository import SavedMediaRepository
from app.domains.saved_media.service import SavedMediaService
from app.main import create_app


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'saved_media_api.db'}")
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


async def _seed_media(database: Database, device_id: UUID, **overrides: Any) -> SavedMedia:
    """Seed one saved media row (plus the command row its FK requires) and commit it.

    Commits explicitly, in its own session, so the HTTP client's request —
    which runs through a *different* session opened per-request by the API
    — sees it.
    """
    async with database.session_factory() as session:
        command = await CommandRepository(session).create(
            Command(device_id=device_id, command_type="camera.snapshot", payload={})
        )
        values: dict[str, Any] = {
            "media_type": MediaType.IMAGE,
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
        media = await SavedMediaService(SavedMediaRepository(session)).record_media(**values)
        await session.commit()
        return media


@pytest.mark.asyncio
async def test_api_lists_empty_when_no_media_exists(database: Database) -> None:
    """A fresh database has no saved media at all, and the page shape stays consistent."""
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/saved-media")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_api_lists_media_with_real_presigned_urls(database: Database) -> None:
    """Listed images carry freshly minted presigned URLs, never raw object keys."""
    device = await _seed_device(database)
    await _seed_media(database, device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/saved-media")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["thumbnail_url"].startswith("https://")
    assert item["image_url"].startswith("https://")
    assert item["thumbnail_url"] != "thumbnails/snapshot.jpg"
    assert item["image_url"] != "originals/snapshot.jpg"


@pytest.mark.asyncio
async def test_api_lists_media_scoped_to_one_device(database: Database) -> None:
    """The device_id filter excludes rows captured by any other device."""
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
    await _seed_media(database, device.id)
    await _seed_media(database, other_device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/saved-media", params={"device_id": str(device.id)})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["device_id"] == str(device.id)


@pytest.mark.asyncio
async def test_api_lists_media_scoped_by_media_type(database: Database) -> None:
    """The media_type filter separates images from videos sharing the same table."""
    device = await _seed_device(database)
    await _seed_media(database, device.id)
    await _seed_media(
        database,
        device.id,
        media_type=MediaType.VIDEO,
        thumbnail_object_key=None,
        duration=42,
        fps=30,
        bitrate=8000,
    )

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        images = await client.get("/saved-media", params={"media_type": "IMAGE"})
        videos = await client.get("/saved-media", params={"media_type": "VIDEO"})

    assert images.json()["total"] == 1
    assert images.json()["items"][0]["media_type"] == "IMAGE"
    assert videos.json()["total"] == 1
    video_item = videos.json()["items"][0]
    assert video_item["media_type"] == "VIDEO"
    assert video_item["duration"] == 42
    assert video_item["thumbnail_url"] == ""
    assert video_item["video_url"].startswith("https://")
    assert video_item["image_url"] == ""


@pytest.mark.asyncio
async def test_api_lists_media_scoped_by_range(database: Database) -> None:
    """The range filter excludes rows captured before the resolved cutoff."""
    device = await _seed_device(database)
    await _seed_media(database, device.id, captured_at=datetime.now(UTC) - timedelta(days=10))
    await _seed_media(database, device.id, captured_at=datetime.now(UTC))

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/saved-media", params={"range": "24h"})

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_api_gets_one_media_row_by_id(database: Database) -> None:
    device = await _seed_device(database)
    media = await _seed_media(database, device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/saved-media/{media.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(media.id)
    assert body["filename"] == "snapshot.jpg"
    assert body["thumbnail_url"].startswith("https://")


@pytest.mark.asyncio
async def test_api_get_missing_media_returns_404_problem_json(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/saved-media/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_api_deletes_a_media_row_then_get_returns_404(database: Database) -> None:
    device = await _seed_device(database)
    media = await _seed_media(database, device.id)

    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        deleted = await client.delete(f"/saved-media/{media.id}")
        assert deleted.status_code == 204

        missing = await client.get(f"/saved-media/{media.id}")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_api_delete_missing_media_returns_404_problem_json(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(f"/saved-media/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_api_returns_503_without_configured_database() -> None:
    """The Saved Media endpoints fail safely when no database is configured."""
    app: FastAPI = create_app(Settings(ENVIRONMENT=Environment.TEST))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/saved-media")
    assert response.status_code == 503
