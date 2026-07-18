"""Application-service and REST tests for live camera streaming.

Every "simulate the agent/dispatcher completing this command" helper below
opens its own fresh database session per poll iteration rather than sharing
one with the service under test. That mirrors production exactly:
``CameraApplicationService`` commits its created command immediately (see its
module docstring) precisely so a *different* session — here, the test's
stand-in for the dispatcher — can see and act on it while the application
service is still polling for a terminal result in its own, separate sessions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI

from app.application.dto.camera_dto import CameraSnapshotDTO
from app.application.dto.device_dto import DeviceDTO
from app.application.events.bus import EventBus
from app.application.exceptions import (
    CameraCommandFailedError,
    CameraCommandTimedOutError,
    CameraDeviceNotFoundError,
)
from app.application.services.camera_service import CameraApplicationService
from app.application.services.device_service import DeviceApplicationService
from app.config.settings import Environment, Settings
from app.core.database import Database
from app.core.mediamtx_jwt import MediaMTXJWTSigner
from app.domains.commands.repository import CommandRepository
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService
from app.main import create_app

START_RESULT = {
    "stream_name": "camera",
    "resolution": "1280x720",
    "fps": 30,
    "started_at": "2026-01-01T00:00:00+00:00",
}
STOP_RESULT = {"duration": 12.5, "frames_sent": 375, "stopped_at": "2026-01-01T00:05:00+00:00"}
SNAPSHOT_RESULT = {
    "bucket": "samslab-snapshots",
    "filename": "snapshot-20260101T000000Z.jpg",
    "original_object_key": "originals/snapshot-20260101T000000Z.jpg",
    "thumbnail_object_key": "thumbnails/snapshot-20260101T000000Z.jpg",
    "etag": '"abc123"',
    "sha256": "a" * 64,
    "width": 1920,
    "height": 1080,
    "size": 204800,
    "captured_at": "2026-01-01T00:00:00+00:00",
}


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'camera.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
def event_bus() -> EventBus:
    """Provide a fresh, unshared event bus so tests can assert on exactly what fired."""
    return EventBus()


@pytest.fixture
def mediamtx_jwt_signer() -> MediaMTXJWTSigner:
    """A throwaway RSA-backed signer — never shared with any real MediaMTX instance."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return MediaMTXJWTSigner(private_key=private_key, key_id="test-key", issuer=None, audience=None)


@pytest.fixture
def camera_app_service(database: Database, event_bus: EventBus) -> CameraApplicationService:
    """Provide a camera application service with fast timeouts suited to tests."""
    return CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="mediamtx.local",
        mediamtx_playback_port=8889,
        stream_name="camera",
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )


@pytest.fixture
async def device(database: Database, event_bus: EventBus) -> DeviceDTO:
    """Register and commit one enabled device that camera commands can target."""
    async with database.session_factory() as session:
        service = DeviceApplicationService(DeviceService(DeviceRepository(session)), event_bus)
        registered = await service.register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "garden-pi",
                    "hostname": "garden-pi.local",
                    "display_name": "Garden Pi",
                }
            )
        )
        await session.commit()
        return registered


async def _complete_pending_command(
    database: Database,
    device_id: UUID,
    command_type: str,
    *,
    result: dict[str, object] | None = None,
    error_message: str | None = None,
    payload_out: dict[str, object] | None = None,
) -> None:
    """Simulate the dispatcher/agent finishing the most recent pending command.

    ``payload_out``, if given, is updated in place with the pending command's
    own payload — the shape the real agent would receive as the COMMAND
    envelope's ``arguments`` (see ``app/dispatcher/delivery.py``).
    """
    for _ in range(200):
        await asyncio.sleep(0.01)
        async with database.session_factory() as session:
            command_service = CommandService(CommandRepository(session))
            pending = await command_service.find_pending(device_id=device_id, limit=10)
            match = next((c for c in pending if c.command_type == command_type), None)
            if match is not None:
                if payload_out is not None:
                    payload_out.update(match.payload)
                await command_service.mark_dispatched(match.id)
                if error_message is not None:
                    await command_service.fail_command(match.id, error_message=error_message)
                else:
                    await command_service.mark_running(match.id)
                    await command_service.complete_command(match.id, result=result or {})
                await session.commit()
                return
    raise AssertionError(f"no pending {command_type} command appeared in time")


# --- CameraApplicationService --------------------------------------------------


async def test_start_stream_waits_for_completion_and_builds_playback_url(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    status, _ = await asyncio.gather(
        camera_app_service.start_stream(),
        _complete_pending_command(database, device.id, "camera.stream.start", result=START_RESULT),
    )
    assert status.running is True
    assert status.stream_name == "camera"
    assert status.playback_url == "http://mediamtx.local:8889/camera/index.m3u8"
    assert status.resolution == "1280x720"
    assert status.fps == 30
    assert status.started_at is not None


async def test_start_stream_without_a_registered_device_raises_not_found(
    camera_app_service: CameraApplicationService,
) -> None:
    with pytest.raises(CameraDeviceNotFoundError):
        await camera_app_service.start_stream()


async def test_start_stream_raises_when_the_command_fails(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    with pytest.raises(CameraCommandFailedError):
        await asyncio.gather(
            camera_app_service.start_stream(),
            _complete_pending_command(
                database,
                device.id,
                "camera.stream.start",
                error_message="camera not detected",
            ),
        )


async def test_start_stream_times_out_when_no_result_arrives(
    database: Database,
    event_bus: EventBus,
    device: DeviceDTO,
) -> None:
    impatient_service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="mediamtx.local",
        mediamtx_playback_port=8889,
        stream_name="camera",
        command_timeout_seconds=0.05,
        command_poll_interval_seconds=0.01,
    )
    with pytest.raises(CameraCommandTimedOutError):
        await impatient_service.start_stream()


async def test_stop_stream_waits_for_completion(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    result, _ = await asyncio.gather(
        camera_app_service.stop_stream(),
        _complete_pending_command(database, device.id, "camera.stream.stop", result=STOP_RESULT),
    )
    assert result.status == "stopped"
    assert result.duration_seconds == 12.5
    assert result.frames_sent == 375
    assert result.stopped_at is not None


async def test_get_status_defaults_to_not_running_when_never_started(
    camera_app_service: CameraApplicationService,
    device: DeviceDTO,
) -> None:
    status = await camera_app_service.get_status()
    assert status.running is False
    assert status.uptime_seconds == 0.0
    assert status.stream_name == "camera"
    assert status.playback_url == "http://mediamtx.local:8889/camera/index.m3u8"


async def test_playback_url_omits_the_port_when_unset(
    database: Database, event_bus: EventBus, device: DeviceDTO
) -> None:
    """A reverse proxy/load balancer terminating the scheme's implicit default
    port (443/80) needs the browser-facing URL to carry no port at all."""
    service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="media.samslab.site",
        mediamtx_playback_port=None,
        mediamtx_playback_scheme="https",
        stream_name="camera",
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )

    status = await service.get_status()

    assert status.playback_url == "https://media.samslab.site/camera/index.m3u8"


async def test_playback_url_uses_https_scheme_with_an_explicit_port(
    database: Database, event_bus: EventBus, device: DeviceDTO
) -> None:
    service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="media.samslab.site",
        mediamtx_playback_port=8443,
        mediamtx_playback_scheme="https",
        stream_name="camera",
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )

    status = await service.get_status()

    assert status.playback_url == "https://media.samslab.site:8443/camera/index.m3u8"


async def test_playback_token_is_none_when_no_signer_is_configured(
    camera_app_service: CameraApplicationService,
    device: DeviceDTO,
) -> None:
    """Unconfigured MediaMTX JWT auth (the ``camera_app_service`` fixture's default) must not error."""
    status = await camera_app_service.get_status()
    assert status.playback_token is None


async def test_playback_token_is_minted_with_a_read_permission_for_the_stream(
    database: Database,
    event_bus: EventBus,
    device: DeviceDTO,
    mediamtx_jwt_signer: MediaMTXJWTSigner,
) -> None:
    service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="media.samslab.site",
        mediamtx_playback_port=None,
        mediamtx_playback_scheme="https",
        mediamtx_jwt_signer=mediamtx_jwt_signer,
        mediamtx_jwt_ttl_seconds=60.0,
        stream_name="camera",
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )

    status = await service.get_status()

    assert status.playback_token is not None
    claims = pyjwt.decode(
        status.playback_token,
        mediamtx_jwt_signer.private_key.public_key(),
        algorithms=["RS256"],
    )
    assert claims["mediamtx_permissions"] == [{"action": "read", "path": "camera"}]


async def test_start_stream_includes_a_publish_token_in_the_command_payload(
    database: Database,
    event_bus: EventBus,
    device: DeviceDTO,
    mediamtx_jwt_signer: MediaMTXJWTSigner,
) -> None:
    """MediaMTX only runs one authMethod, so once reads require a JWT, the agent's
    RTSP publish must authenticate with one too — delivered via the command payload."""
    service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="media.samslab.site",
        mediamtx_playback_port=None,
        mediamtx_playback_scheme="https",
        mediamtx_jwt_signer=mediamtx_jwt_signer,
        mediamtx_jwt_ttl_seconds=60.0,
        mediamtx_jwt_publish_ttl_seconds=3600.0,
        stream_name="camera",
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )
    captured_payload: dict[str, object] = {}

    await asyncio.gather(
        service.start_stream(),
        _complete_pending_command(
            database,
            device.id,
            "camera.stream.start",
            result=START_RESULT,
            payload_out=captured_payload,
        ),
    )

    publish_token = captured_payload["mediamtx_publish_token"]
    assert isinstance(publish_token, str)
    claims = pyjwt.decode(
        publish_token,
        mediamtx_jwt_signer.private_key.public_key(),
        algorithms=["RS256"],
    )
    assert claims["mediamtx_permissions"] == [{"action": "publish", "path": "camera"}]
    assert claims["exp"] - claims["iat"] == 3600


async def test_start_stream_omits_publish_token_when_signer_not_configured(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    captured_payload: dict[str, object] = {}

    await asyncio.gather(
        camera_app_service.start_stream(),
        _complete_pending_command(
            database,
            device.id,
            "camera.stream.start",
            result=START_RESULT,
            payload_out=captured_payload,
        ),
    )

    assert captured_payload == {}


async def test_get_status_reports_running_after_a_completed_start(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    await asyncio.gather(
        camera_app_service.start_stream(),
        _complete_pending_command(database, device.id, "camera.stream.start", result=START_RESULT),
    )
    status = await camera_app_service.get_status()
    assert status.running is True
    assert status.resolution == "1280x720"
    assert status.uptime_seconds >= 0.0


async def test_get_status_reports_stopped_after_start_then_stop(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    await asyncio.gather(
        camera_app_service.start_stream(),
        _complete_pending_command(database, device.id, "camera.stream.start", result=START_RESULT),
    )
    await asyncio.gather(
        camera_app_service.stop_stream(),
        _complete_pending_command(database, device.id, "camera.stream.stop", result=STOP_RESULT),
    )
    status = await camera_app_service.get_status()
    assert status.running is False


# --- CameraApplicationService.capture_snapshot ---------------------------------


async def test_capture_snapshot_waits_for_completion_and_persists_metadata(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    """capture_snapshot returns metadata-only DTO and persists the full row via SnapshotService."""
    dto, _ = await asyncio.gather(
        camera_app_service.capture_snapshot(),
        _complete_pending_command(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )
    assert isinstance(dto, CameraSnapshotDTO)
    assert dto.device_id == device.id
    assert dto.filename == SNAPSHOT_RESULT["filename"]
    assert dto.width == 1920
    assert dto.height == 1080
    assert dto.size == 204800
    assert dto.captured_at is not None

    async with database.session_factory() as session:
        snapshot_service = SnapshotService(SnapshotRepository(session))
        persisted = await snapshot_service.get_snapshot(dto.id)
    assert persisted.command_id == dto.command_id
    assert persisted.bucket == SNAPSHOT_RESULT["bucket"]
    assert persisted.original_object_key == SNAPSHOT_RESULT["original_object_key"]
    assert persisted.thumbnail_object_key == SNAPSHOT_RESULT["thumbnail_object_key"]
    assert persisted.sha256 == SNAPSHOT_RESULT["sha256"]


async def test_capture_snapshot_without_a_registered_device_raises_not_found(
    camera_app_service: CameraApplicationService,
) -> None:
    with pytest.raises(CameraDeviceNotFoundError):
        await camera_app_service.capture_snapshot()


async def test_capture_snapshot_raises_when_the_command_fails(
    camera_app_service: CameraApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    with pytest.raises(CameraCommandFailedError):
        await asyncio.gather(
            camera_app_service.capture_snapshot(),
            _complete_pending_command(
                database, device.id, "camera.snapshot", error_message="camera not detected"
            ),
        )


async def test_capture_snapshot_times_out_when_no_result_arrives(
    database: Database,
    event_bus: EventBus,
    device: DeviceDTO,
) -> None:
    impatient_service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="mediamtx.local",
        mediamtx_playback_port=8889,
        stream_name="camera",
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.01,
        snapshot_command_timeout_seconds=0.05,
    )
    with pytest.raises(CameraCommandTimedOutError):
        await impatient_service.capture_snapshot()


async def test_capture_snapshot_uses_its_own_timeout_not_the_stream_command_timeout(
    database: Database,
    event_bus: EventBus,
    device: DeviceDTO,
) -> None:
    """A completion slower than start_stream's timeout still succeeds within the longer,
    snapshot-specific timeout, proving _wait_for_terminal's timeout_seconds override is
    actually used here rather than falling back to self._command_timeout_seconds."""
    service = CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host="mediamtx.local",
        mediamtx_playback_port=8889,
        stream_name="camera",
        command_timeout_seconds=0.05,
        command_poll_interval_seconds=0.02,
        snapshot_command_timeout_seconds=2.0,
    )

    async def _complete_after_delay() -> None:
        await asyncio.sleep(0.15)
        await _complete_pending_command(
            database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT
        )

    dto, _ = await asyncio.gather(service.capture_snapshot(), _complete_after_delay())
    assert dto.filename == SNAPSHOT_RESULT["filename"]


# --- REST API -------------------------------------------------------------


def _app_for(database: Database) -> FastAPI:
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            MEDIAMTX_HOST="mediamtx.local",
            MEDIAMTX_PLAYBACK_PORT=8889,
            CAMERA_STREAM_NAME="camera",
            CAMERA_COMMAND_TIMEOUT_SECONDS=2.0,
            CAMERA_COMMAND_POLL_INTERVAL_SECONDS=0.02,
        )
    )
    app.state.container.database.override(database)
    return app


async def test_api_start_stop_and_status_round_trip(database: Database, device: DeviceDTO) -> None:
    """The REST endpoints create commands, wait for them, and shape a stable response."""
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start_response, _ = await asyncio.gather(
            client.post("/camera/start"),
            _complete_pending_command(
                database, device.id, "camera.stream.start", result=START_RESULT
            ),
        )
        assert start_response.status_code == 200
        body = start_response.json()
        assert body["running"] is True
        assert body["playback_url"] == "http://mediamtx.local:8889/camera/index.m3u8"
        assert body["playback_token"] is None
        assert body["stream_name"] == "camera"
        assert body["resolution"] == "1280x720"
        assert body["fps"] == 30

        status_response = await client.get("/camera/status")
        assert status_response.status_code == 200
        assert status_response.json()["running"] is True

        stop_response, _ = await asyncio.gather(
            client.post("/camera/stop"),
            _complete_pending_command(
                database, device.id, "camera.stream.stop", result=STOP_RESULT
            ),
        )
        assert stop_response.status_code == 200
        stop_body = stop_response.json()
        assert stop_body["status"] == "stopped"
        assert stop_body["frames_sent"] == 375

        final_status = await client.get("/camera/status")
        assert final_status.json()["running"] is False


def _base64_pem_private_key(private_key: rsa.RSAPrivateKey) -> str:
    from base64 import b64encode

    from cryptography.hazmat.primitives import serialization

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return b64encode(pem).decode("ascii")


async def test_api_includes_a_playback_token_and_serves_its_matching_jwks(
    database: Database, device: DeviceDTO
) -> None:
    """A configured MediaMTX JWT key must produce a token verifiable against our own JWKS route."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            MEDIAMTX_HOST="mediamtx.local",
            MEDIAMTX_PLAYBACK_PORT=8889,
            MEDIAMTX_JWT_PRIVATE_KEY=_base64_pem_private_key(private_key),
            MEDIAMTX_JWT_KEY_ID="test-key",
            CAMERA_STREAM_NAME="camera",
            CAMERA_COMMAND_TIMEOUT_SECONDS=2.0,
            CAMERA_COMMAND_POLL_INTERVAL_SECONDS=0.02,
        )
    )
    app.state.container.database.override(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start_response, _ = await asyncio.gather(
            client.post("/camera/start"),
            _complete_pending_command(
                database, device.id, "camera.stream.start", result=START_RESULT
            ),
        )
        token = start_response.json()["playback_token"]
        assert token is not None

        jwks_response = await client.get("/.well-known/mediamtx-jwks.json")
        assert jwks_response.status_code == 200
        keys = jwks_response.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["kid"] == "test-key"
        assert keys[0]["kty"] == "RSA"

        claims = pyjwt.decode(token, private_key.public_key(), algorithms=["RS256"])
        assert claims["mediamtx_permissions"] == [{"action": "read", "path": "camera"}]


async def test_jwks_endpoint_returns_an_empty_key_set_when_unconfigured(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/.well-known/mediamtx-jwks.json")
        assert response.status_code == 200
        assert response.json() == {"keys": []}


async def test_api_returns_404_when_no_device_is_registered(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/camera/start")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_api_maps_a_failed_camera_command_to_409(
    database: Database, device: DeviceDTO
) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response, _ = await asyncio.gather(
            client.post("/camera/start"),
            _complete_pending_command(
                database, device.id, "camera.stream.start", error_message="camera not detected"
            ),
        )
        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_api_captures_snapshot_and_returns_metadata_only(
    database: Database, device: DeviceDTO
) -> None:
    """POST /camera/snapshot returns metadata-only fields, never a URL or bucket name."""
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response, _ = await asyncio.gather(
            client.post("/camera/snapshot"),
            _complete_pending_command(
                database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["device_id"] == str(device.id)
        assert body["filename"] == SNAPSHOT_RESULT["filename"]
        assert body["width"] == 1920
        assert body["height"] == 1080
        assert body["size"] == 204800
        assert "thumbnail_url" not in body
        assert "image_url" not in body
        assert "bucket" not in body


async def test_api_snapshot_returns_404_when_no_device_is_registered(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/camera/snapshot")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_api_maps_a_failed_snapshot_command_to_409(
    database: Database, device: DeviceDTO
) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response, _ = await asyncio.gather(
            client.post("/camera/snapshot"),
            _complete_pending_command(
                database, device.id, "camera.snapshot", error_message="camera not detected"
            ),
        )
        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")
