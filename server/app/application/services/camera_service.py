"""Application service orchestrating live camera streaming through the Command domain.

There is no Camera domain and no camera-specific persistence: this service is a
pure orchestration layer over the Command and Device domains, translating
"start/stop/status" use cases into ``camera.stream.start``/``camera.stream.stop``
commands and back into a stream status shape the frontend can render directly.

Like ``CommandGateway`` in ``app/dispatcher/dispatcher.py``, this service opens
one short-lived, transactional ``CommandApplicationService``/
``DeviceApplicationService`` per operation rather than holding a single
request-scoped session across its whole start/stop workflow. That is not
optional here: creating a command and then waiting for a *different* process
(the dispatcher, and beyond it the device) to act on it requires the create to
actually commit before the wait begins — an open transaction would hide the
new command from everyone else and deadlock the wait forever.

The browser never talks to the Raspberry Pi. It only ever talks to this
service's REST controller, which returns a ``playback_url`` (the MediaMTX HLS
manifest) built from server-side MediaMTX configuration, plus a short-lived
``playback_token`` (see ``app/core/mediamtx_jwt.py``) the frontend attaches
as an Authorization header on every manifest/segment request. When MediaMTX
JWT auth is configured, ``start_stream`` also mints a longer-lived *publish*
JWT and hands it to the agent inside the ``camera.stream.start`` command's
payload — MediaMTX only runs one ``authMethod`` at a time, so the agent's
RTSP publish connection needs a JWT too once reads require one.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.camera_dto import CameraSnapshotDTO, CameraStatusDTO, CameraStopDTO
from app.application.dto.command_dto import CommandDetailDTO
from app.application.events.bus import EventBus
from app.application.exceptions import (
    CameraCommandFailedError,
    CameraCommandTimedOutError,
    CameraDeviceNotFoundError,
)
from app.application.mappers.snapshot_mapper import to_camera_snapshot_dto
from app.application.services.command_artifacts import record_snapshot_from_command
from app.application.services.command_service import CommandApplicationService
from app.application.services.device_service import DeviceApplicationService
from app.core.database import Database
from app.core.mediamtx_jwt import MediaMTXJWTSigner
from app.domains.commands.models import TERMINAL_STATUSES, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.service import DeviceService

CAMERA_STREAM_START = "camera.stream.start"
CAMERA_STREAM_STOP = "camera.stream.stop"
CAMERA_SNAPSHOT = "camera.snapshot"


class CameraApplicationService:
    """Expose camera stream start/stop/status use cases as DTOs."""

    def __init__(
        self,
        *,
        database: Database,
        event_bus: EventBus,
        mediamtx_host: str,
        mediamtx_playback_port: int | None,
        mediamtx_playback_scheme: str = "http",
        mediamtx_jwt_signer: MediaMTXJWTSigner | None = None,
        mediamtx_jwt_ttl_seconds: float = 60.0,
        mediamtx_jwt_publish_ttl_seconds: float = 86400.0,
        stream_name: str,
        command_timeout_seconds: float,
        command_poll_interval_seconds: float,
        snapshot_command_timeout_seconds: float = 60.0,
    ) -> None:
        """Bind to the shared database/event bus and the MediaMTX playback configuration."""
        self._database = database
        self._event_bus = event_bus
        self._mediamtx_host = mediamtx_host
        self._mediamtx_playback_port = mediamtx_playback_port
        self._mediamtx_playback_scheme = mediamtx_playback_scheme
        self._mediamtx_jwt_signer = mediamtx_jwt_signer
        self._mediamtx_jwt_ttl_seconds = mediamtx_jwt_ttl_seconds
        self._mediamtx_jwt_publish_ttl_seconds = mediamtx_jwt_publish_ttl_seconds
        self._stream_name = stream_name
        self._command_timeout_seconds = command_timeout_seconds
        self._command_poll_interval_seconds = command_poll_interval_seconds
        self._snapshot_command_timeout_seconds = snapshot_command_timeout_seconds

    async def start_stream(self) -> CameraStatusDTO:
        """Issue ``camera.stream.start`` and wait for the device to confirm it's live."""
        device_id = await self._require_primary_device_id()
        payload = self._start_command_payload()
        command_id = await self._create_command(device_id, CAMERA_STREAM_START, payload=payload)
        completed = await self._wait_for_terminal(command_id)
        result = completed.result.result if completed.result else {}
        stream_name = str(result.get("stream_name", self._stream_name))
        started_at = self._parse_timestamp(result.get("started_at")) or completed.completed_at
        return CameraStatusDTO(
            running=True,
            stream_name=stream_name,
            playback_url=self._playback_url(stream_name),
            playback_token=self._mint_playback_token(stream_name),
            resolution=result.get("resolution"),
            fps=result.get("fps"),
            started_at=started_at,
            uptime_seconds=0.0,
            viewer_count=0,
        )

    async def stop_stream(self) -> CameraStopDTO:
        """Issue ``camera.stream.stop`` and wait for the device to confirm it's stopped."""
        device_id = await self._require_primary_device_id()
        command_id = await self._create_command(device_id, CAMERA_STREAM_STOP)
        completed = await self._wait_for_terminal(command_id)
        result = completed.result.result if completed.result else {}
        return CameraStopDTO(
            status="stopped",
            duration_seconds=result.get("duration"),
            frames_sent=result.get("frames_sent"),
            stopped_at=self._parse_timestamp(result.get("stopped_at")) or completed.completed_at,
        )

    async def get_status(self) -> CameraStatusDTO:
        """Derive current stream state from the most recent start/stop commands."""
        device_id = await self._require_primary_device_id()
        latest_start = await self._latest_completed_command(device_id, CAMERA_STREAM_START)
        latest_stop = await self._latest_completed_command(device_id, CAMERA_STREAM_STOP)

        running = latest_start is not None and (
            latest_stop is None or _completed_at(latest_start) > _completed_at(latest_stop)
        )
        if not running or latest_start is None:
            return CameraStatusDTO(
                running=False,
                stream_name=self._stream_name,
                playback_url=self._playback_url(self._stream_name),
                playback_token=self._mint_playback_token(self._stream_name),
            )

        result = latest_start.result.result if latest_start.result else {}
        stream_name = str(result.get("stream_name", self._stream_name))
        started_at = self._parse_timestamp(result.get("started_at")) or _completed_at(latest_start)
        uptime_seconds = max(0.0, (datetime.now(UTC) - started_at).total_seconds())
        return CameraStatusDTO(
            running=True,
            stream_name=stream_name,
            playback_url=self._playback_url(stream_name),
            playback_token=self._mint_playback_token(stream_name),
            resolution=result.get("resolution"),
            fps=result.get("fps"),
            started_at=started_at,
            uptime_seconds=uptime_seconds,
            viewer_count=0,
        )

    async def capture_snapshot(self) -> CameraSnapshotDTO:
        """Issue ``camera.snapshot``, wait for it to complete, and persist its metadata.

        Independent of streaming — see ``docs/agent/CAMERA.md`` and
        ``CameraService.capture_snapshot`` (agent-side) for the
        reuse-live-session-or-open-fresh-one behavior this command triggers.
        Waits longer than ``start_stream``/``stop_stream`` (see
        ``_snapshot_command_timeout_seconds``) since a standalone capture may
        need to open the camera, capture, encode, and upload two files to S3
        before it completes. Never touches S3 itself — only
        ``SnapshotApplicationService`` (``GET /snapshots``) ever mints a
        presigned URL for the resulting image.
        """
        device_id = await self._require_primary_device_id()
        command_id = await self._create_command(device_id, CAMERA_SNAPSHOT)
        completed = await self._wait_for_terminal(
            command_id, timeout_seconds=self._snapshot_command_timeout_seconds
        )
        result = completed.result.result if completed.result else {}
        # workflow_run_id=None: this call always originates from a direct
        # Dashboard action, never a Workflow's Command Task — see
        # WorkflowApplicationService._execute_command_step for the other
        # caller of this same shared helper.
        snapshot = await record_snapshot_from_command(
            self._database,
            command_type=CAMERA_SNAPSHOT,
            device_id=device_id,
            command_id=command_id,
            result=result,
            workflow_run_id=None,
        )
        assert snapshot is not None  # CAMERA_SNAPSHOT always produces one
        return to_camera_snapshot_dto(snapshot)

    # --- per-operation session helpers, mirroring app/dispatcher/dispatcher.py's CommandGateway ---

    def _build_command_service(self, session: AsyncSession) -> CommandApplicationService:
        return CommandApplicationService(
            CommandService(CommandRepository(session)),
            DeviceService(DeviceRepository(session)),
            self._event_bus,
        )

    def _build_device_service(self, session: AsyncSession) -> DeviceApplicationService:
        return DeviceApplicationService(DeviceService(DeviceRepository(session)), self._event_bus)

    async def _require_primary_device_id(self) -> UUID:
        """Return the single MVP device's id, or raise if none is registered."""
        async with self._database.session_factory() as session:
            service = self._build_device_service(session)
            page = await service.list_devices(
                status=None, enabled=None, capability=None, search=None, offset=0, limit=1
            )
            await session.commit()
        if not page.items:
            raise CameraDeviceNotFoundError("No registered device available for camera streaming")
        return page.items[0].id

    async def _create_command(
        self, device_id: UUID, command_type: str, *, payload: dict[str, object] | None = None
    ) -> UUID:
        """Create and commit a command so other sessions/processes can see it immediately."""
        async with self._database.session_factory() as session:
            service = self._build_command_service(session)
            command = await service.create_command(
                CommandCreate(device_id=device_id, command_type=command_type, payload=payload or {})
            )
            await session.commit()
            return command.id

    async def _get_command(self, command_id: UUID) -> CommandDetailDTO:
        """Fetch a command in its own fresh transaction, so it sees other sessions' commits."""
        async with self._database.session_factory() as session:
            service = self._build_command_service(session)
            command = await service.get_command(command_id)
            await session.commit()
            return command

    async def _latest_completed_command(
        self, device_id: UUID, command_type: str
    ) -> CommandDetailDTO | None:
        """Return the most recently completed command of a type, or None."""
        async with self._database.session_factory() as session:
            service = self._build_command_service(session)
            page = await service.list_commands(
                status=CommandStatus.COMPLETED,
                device_id=device_id,
                priority=None,
                command_type=command_type,
                created_after=None,
                created_before=None,
                offset=0,
                limit=1,
                sort="-created_at",
            )
            if not page.items:
                await session.commit()
                return None
            command = await service.get_command(page.items[0].id)
            await session.commit()
            return command

    async def _wait_for_terminal(
        self, command_id: UUID, *, timeout_seconds: float | None = None
    ) -> CommandDetailDTO:
        """Poll a command until it reaches a terminal state, or raise once the wait expires.

        ``timeout_seconds`` defaults to ``self._command_timeout_seconds`` (the
        existing ``start_stream``/``stop_stream`` behavior); ``capture_snapshot``
        passes a longer, snapshot-specific timeout since camera init + capture
        + two S3 uploads can take longer than a plain stream toggle.
        """
        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else self._command_timeout_seconds
        )
        deadline = time.monotonic() + effective_timeout
        while True:
            command = await self._get_command(command_id)
            if command.status in TERMINAL_STATUSES:
                if command.status != CommandStatus.COMPLETED:
                    raise CameraCommandFailedError(
                        f"Command {command_id} ended in status {command.status}"
                    )
                return command
            if time.monotonic() >= deadline:
                raise CameraCommandTimedOutError(
                    f"Command {command_id} did not complete within {effective_timeout}s"
                )
            await asyncio.sleep(self._command_poll_interval_seconds)

    def _playback_url(self, stream_name: str) -> str:
        """Build the browser-facing MediaMTX HLS manifest URL for a stream name.

        Points at the raw ``index.m3u8`` manifest, not MediaMTX's embedded
        HTML player page — the frontend drives playback itself through
        hls.js so it can attach the Authorization header from
        ``playback_token`` to every manifest/segment request (a plain
        ``<iframe>``/``<video src>`` load has no way to carry that header,
        and embedding ``user:pass@host`` credentials in the URL itself no
        longer works in Chrome). No port is appended when
        ``mediamtx_playback_port`` is unset — for a reverse proxy/load
        balancer that terminates the scheme's implicit default port (443 for
        https, 80 for http) and forwards to MediaMTX's real port internally,
        the browser never needs to see that port.
        """
        host = self._mediamtx_host
        if self._mediamtx_playback_port is not None:
            host = f"{host}:{self._mediamtx_playback_port}"
        return f"{self._mediamtx_playback_scheme}://{host}/{stream_name}/index.m3u8"

    def _mint_playback_token(self, stream_name: str) -> str | None:
        """A fresh, short-lived MediaMTX read JWT, or None when JWT auth isn't configured."""
        if self._mediamtx_jwt_signer is None:
            return None
        return self._mediamtx_jwt_signer.mint_read_token(
            stream_path=stream_name, ttl_seconds=self._mediamtx_jwt_ttl_seconds
        )

    def _start_command_payload(self) -> dict[str, object]:
        """The ``camera.stream.start`` command payload, carrying a publish JWT when configured.

        MediaMTX only runs one ``authMethod`` at a time, so once a
        deployment sets it to ``jwt`` (required for browser reads — see
        ``_mint_playback_token``), the agent's RTSP *publish* connection must
        authenticate with a JWT too; there's no "internal database" method
        left running alongside it to fall back to for just that one action.
        Omitted (empty payload) when MediaMTX JWT auth isn't configured
        server-side, in which case the agent falls back to its own
        statically configured MEDIAMTX_USERNAME/MEDIAMTX_PASSWORD.
        """
        if self._mediamtx_jwt_signer is None:
            return {}
        token = self._mediamtx_jwt_signer.mint_publish_token(
            stream_path=self._stream_name, ttl_seconds=self._mediamtx_jwt_publish_ttl_seconds
        )
        return {"mediamtx_publish_token": token}

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        """Best-effort parse of a device-reported ISO 8601 timestamp string."""
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _completed_at(command: CommandDetailDTO) -> datetime:
    """Extract a non-null ``completed_at`` from a terminal ``CommandDetailDTO``."""
    assert command.completed_at is not None  # terminal commands always set this
    return command.completed_at
