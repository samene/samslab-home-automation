"""Tests for application services: cross-domain orchestration, DTOs, and event publishing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.command_dto import CommandDetailDTO
from app.application.dto.device_dto import CapabilityDTO, DeviceDTO
from app.application.dto.saved_media_dto import SavedMediaDTO, SavedMediaPageDTO
from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    CommandCompleted,
    CommandCreated,
    CommandFailed,
    DeviceHeartbeat,
    DeviceRegistered,
)
from app.application.exceptions import (
    ApplicationValidationError,
    CommandNotFoundError,
    DeviceAlreadyExistsError,
    DeviceDisabledError,
    DeviceNotFoundError,
    DuplicateCapabilityError,
    InvalidCommandStateError,
    InvalidHeartbeatError,
    SavedMediaNotFoundError,
)
from app.application.services.command_service import CommandApplicationService
from app.application.services.device_service import DeviceApplicationService
from app.application.services.health_service import HealthApplicationService
from app.application.services.saved_media_service import SavedMediaApplicationService
from app.core.database import Database
from app.core.s3_client import S3Client
from app.domains.commands.exceptions import CommandNotFound
from app.domains.commands.models import Command, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import (
    CapabilityInput,
    CapabilityReplace,
    DeviceCreate,
    DeviceUpdate,
    HeartbeatInput,
)
from app.domains.devices.service import DeviceService
from app.domains.saved_media.exceptions import SavedMediaNotFound
from app.domains.saved_media.models import MediaType, SavedMedia
from app.domains.saved_media.repository import SavedMediaRepository
from app.domains.saved_media.service import SavedMediaService
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowCreate
from app.domains.workflows.service import WorkflowService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'application.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """Provide one transaction-scoped session shared by a test's fixtures and body."""
    async with database.session_factory() as session:
        yield session
        try:
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.fixture
def event_bus() -> EventBus:
    """Provide a fresh, unshared event bus so tests can assert on exactly what fired."""
    return EventBus()


@pytest.fixture
def device_app_service(session: AsyncSession, event_bus: EventBus) -> DeviceApplicationService:
    """Provide a device application service wired to the shared session and event bus."""
    return DeviceApplicationService(DeviceService(DeviceRepository(session)), event_bus)


@pytest.fixture
def command_app_service(session: AsyncSession, event_bus: EventBus) -> CommandApplicationService:
    """Provide a command application service wired to both domain services."""
    return CommandApplicationService(
        CommandService(CommandRepository(session)),
        DeviceService(DeviceRepository(session)),
        event_bus,
    )


def device_payload(name: str = "garden-node") -> dict[str, object]:
    """Build a valid device registration payload."""
    return {
        "device_name": name,
        "hostname": f"{name}.local",
        "display_name": "Garden node",
        "capabilities": [{"capability": "gpio", "version": "1.0"}],
    }


def command_payload(device_id: UUID, **overrides: object) -> dict[str, object]:
    """Build a valid, generic command request."""
    payload: dict[str, object] = {
        "device_id": str(device_id),
        "command_type": "pump.start",
        "payload": {"duration_s": 30},
    }
    payload.update(overrides)
    return payload


class _Recorder:
    """A tiny test double that records every event it receives."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, event: object) -> None:
        self.received.append(event)


# --- DeviceApplicationService --------------------------------------------------


@pytest.mark.asyncio
async def test_device_service_register_returns_dto_and_publishes_event(
    device_app_service: DeviceApplicationService, event_bus: EventBus
) -> None:
    """Registration returns a DTO (never a SQLAlchemy model) and publishes DeviceRegistered."""
    recorder = _Recorder()
    event_bus.subscribe(DeviceRegistered, recorder)

    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))

    assert isinstance(device, DeviceDTO)
    assert isinstance(device.capabilities[0], CapabilityDTO)  # a DTO tree, never ORM rows
    assert len(recorder.received) == 1
    event = recorder.received[0]
    assert isinstance(event, DeviceRegistered)
    assert event.device_id == device.id
    assert event.device_name == "garden-node"


@pytest.mark.asyncio
async def test_device_service_translates_duplicate_name_to_application_error(
    device_app_service: DeviceApplicationService,
) -> None:
    """A domain DeviceAlreadyExists error surfaces as the application equivalent."""
    await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    with pytest.raises(DeviceAlreadyExistsError):
        await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))


@pytest.mark.asyncio
async def test_device_service_get_missing_device_raises_application_not_found(
    device_app_service: DeviceApplicationService,
) -> None:
    """A missing device raises the application's not-found error, not the domain's."""
    with pytest.raises(DeviceNotFoundError):
        await device_app_service.get_device(uuid4())


@pytest.mark.asyncio
async def test_device_service_list_devices_validates_pagination_centrally(
    device_app_service: DeviceApplicationService,
) -> None:
    """Out-of-bounds pagination is rejected by the application layer, not a controller."""
    with pytest.raises(ApplicationValidationError):
        await device_app_service.list_devices(
            status=None, enabled=None, capability=None, search=None, offset=0, limit=1000
        )


@pytest.mark.asyncio
async def test_device_service_heartbeat_publishes_event(
    device_app_service: DeviceApplicationService, event_bus: EventBus
) -> None:
    """A successful heartbeat publishes DeviceHeartbeat with the recorded status."""
    recorder = _Recorder()
    event_bus.subscribe(DeviceHeartbeat, recorder)
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))

    updated = await device_app_service.heartbeat(
        device.id,
        HeartbeatInput(status="ONLINE", agent_version="1.0", protocol_version="1.0"),
    )

    assert updated.status.value == "ONLINE"
    assert len(recorder.received) == 1
    assert recorder.received[0].status == "ONLINE"


@pytest.mark.asyncio
async def test_device_service_heartbeat_on_disabled_device_translates_error(
    device_app_service: DeviceApplicationService,
) -> None:
    """A disabled device's heartbeat rejection surfaces as an application error."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    await device_app_service.disable(device.id)
    with pytest.raises(InvalidHeartbeatError):
        await device_app_service.heartbeat(
            device.id,
            HeartbeatInput(status="ONLINE", agent_version="1.0", protocol_version="1.0"),
        )


@pytest.mark.asyncio
async def test_device_service_get_device_returns_the_registered_device(
    device_app_service: DeviceApplicationService,
) -> None:
    """The successful get_device path returns the matching DTO."""
    registered = await device_app_service.register_device(
        DeviceCreate.model_validate(device_payload())
    )
    fetched = await device_app_service.get_device(registered.id)
    assert fetched.id == registered.id
    assert fetched.device_name == "garden-node"


@pytest.mark.asyncio
async def test_device_service_missing_device_translates_to_not_found_on_every_use_case(
    device_app_service: DeviceApplicationService,
) -> None:
    """update/enable/disable/delete on a missing device all translate to the same error."""
    missing_id = uuid4()
    with pytest.raises(DeviceNotFoundError):
        await device_app_service.update_device(missing_id, DeviceUpdate())
    with pytest.raises(DeviceNotFoundError):
        await device_app_service.enable(missing_id)
    with pytest.raises(DeviceNotFoundError):
        await device_app_service.disable(missing_id)
    with pytest.raises(DeviceNotFoundError):
        await device_app_service.delete(missing_id)


@pytest.mark.asyncio
async def test_device_service_replace_capabilities_translates_duplicate_error(
    device_app_service: DeviceApplicationService,
) -> None:
    """A duplicate capability replacement surfaces as an application conflict."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    with pytest.raises(DuplicateCapabilityError):
        await device_app_service.replace_capabilities(
            device.id,
            [
                CapabilityInput(capability="gpio", version="1"),
                CapabilityInput(capability="gpio", version="2"),
            ],
        )


@pytest.mark.asyncio
async def test_device_service_update_enable_disable_delete_round_trip(
    device_app_service: DeviceApplicationService,
) -> None:
    """The remaining device use cases return DTOs end to end."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    updated = await device_app_service.update_device(
        device.id, DeviceUpdate(display_name="Greenhouse node")
    )
    assert updated.display_name == "Greenhouse node"

    disabled = await device_app_service.disable(device.id)
    assert disabled.enabled is False

    enabled = await device_app_service.enable(device.id)
    assert enabled.enabled is True

    await device_app_service.delete(device.id)
    with pytest.raises(DeviceNotFoundError):
        await device_app_service.get_device(device.id)


@pytest.mark.asyncio
async def test_device_service_list_devices_returns_page_dto(
    device_app_service: DeviceApplicationService,
) -> None:
    """list_devices returns a bounded page of DTOs."""
    await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    page = await device_app_service.list_devices(
        status=None, enabled=None, capability=None, search=None, offset=0, limit=10
    )
    assert page.total == 1
    assert len(page.items) == 1
    assert isinstance(page.items[0], DeviceDTO)


@pytest.mark.asyncio
async def test_device_service_replace_capabilities_via_capability_replace_schema(
    device_app_service: DeviceApplicationService,
) -> None:
    """The replace-capabilities use case accepts the schema's validated capability list."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    replaced = await device_app_service.replace_capabilities(
        device.id,
        CapabilityReplace.model_validate(
            {"capabilities": [{"capability": "camera", "version": "1.0"}]}
        ).capabilities,
    )
    assert [c.capability for c in replaced.capabilities] == ["camera"]


# --- CommandApplicationService --------------------------------------------------


@pytest.mark.asyncio
async def test_command_service_create_requires_existing_device(
    command_app_service: CommandApplicationService,
) -> None:
    """Confirming the device exists is an application-layer concern now, not the domain's."""
    with pytest.raises(DeviceNotFoundError):
        await command_app_service.create_command(
            CommandCreate.model_validate(command_payload(uuid4()))
        )


@pytest.mark.asyncio
async def test_command_service_create_rejects_disabled_device(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    """A disabled device's block on new commands is enforced by the application layer."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    await device_app_service.disable(device.id)
    with pytest.raises(DeviceDisabledError):
        await command_app_service.create_command(
            CommandCreate.model_validate(command_payload(device.id))
        )


@pytest.mark.asyncio
async def test_command_service_create_returns_dto_and_publishes_event(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
    event_bus: EventBus,
) -> None:
    """A successful creation returns a DTO and publishes CommandCreated."""
    recorder = _Recorder()
    event_bus.subscribe(CommandCreated, recorder)
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))

    command = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )

    assert isinstance(command, CommandDetailDTO)
    assert command.status is CommandStatus.PENDING
    assert len(recorder.received) == 1
    assert recorder.received[0].command_id == command.id


@pytest.mark.asyncio
async def test_command_service_get_missing_command_raises_application_not_found(
    command_app_service: CommandApplicationService,
) -> None:
    """A missing command raises the application's not-found error, not the domain's."""
    with pytest.raises(CommandNotFoundError):
        await command_app_service.get_command(uuid4())


@pytest.mark.asyncio
async def test_command_service_get_command_returns_the_created_command(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    """The successful get_command path returns the matching detail DTO."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    created = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    fetched = await command_app_service.get_command(created.id)
    assert fetched.id == created.id
    assert fetched.command_type == "pump.start"


@pytest.mark.asyncio
async def test_command_service_cancel_command_succeeds_and_returns_dto(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    """Cancelling a pending command succeeds and returns the updated detail DTO."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    command = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    cancelled = await command_app_service.cancel_command(command.id, reason="operator abort")
    assert cancelled.status is CommandStatus.CANCELLED


@pytest.mark.asyncio
async def test_command_service_delete_command_removes_a_terminal_command(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    """Deleting a cancelled (terminal) command makes it unreachable afterward."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    command = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    await command_app_service.cancel_command(command.id)

    await command_app_service.delete_command(command.id)

    with pytest.raises(CommandNotFoundError):
        await command_app_service.get_command(command.id)


@pytest.mark.asyncio
async def test_command_service_delete_command_translates_not_found_and_state_errors(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    with pytest.raises(CommandNotFoundError):
        await command_app_service.delete_command(uuid4())

    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    command = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    with pytest.raises(InvalidCommandStateError):
        await command_app_service.delete_command(command.id)


@pytest.mark.asyncio
async def test_command_service_missing_command_translates_to_not_found_on_every_transition(
    command_app_service: CommandApplicationService,
) -> None:
    """mark_dispatched/mark_running/complete/fail on a missing command all translate."""
    missing_id = uuid4()
    with pytest.raises(CommandNotFoundError):
        await command_app_service.mark_dispatched(missing_id)
    with pytest.raises(CommandNotFoundError):
        await command_app_service.mark_running(missing_id)
    with pytest.raises(CommandNotFoundError):
        await command_app_service.complete_command(missing_id, result={})
    with pytest.raises(CommandNotFoundError):
        await command_app_service.fail_command(missing_id, error_message="boom")


@pytest.mark.asyncio
async def test_command_service_create_command_translates_a_domain_error(
    session: AsyncSession,
    device_app_service: DeviceApplicationService,
    event_bus: EventBus,
) -> None:
    """create_command's own domain-error branch is reached via a stubbed domain service.

    The real domain ``create_command`` never raises today (no cross-domain check
    remains at that layer), so this uses a minimal stub to prove the translation
    still fires correctly if a future domain change ever raises here.
    """
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))

    class _FailingCommandService(CommandService):
        async def create_command(self, request: CommandCreate) -> Command:
            raise CommandNotFound("simulated failure")

    stub_service = CommandApplicationService(
        _FailingCommandService(CommandRepository(session)),
        DeviceService(DeviceRepository(session)),
        event_bus,
    )
    with pytest.raises(CommandNotFoundError):
        await stub_service.create_command(CommandCreate.model_validate(command_payload(device.id)))


@pytest.mark.asyncio
async def test_command_service_cancel_after_terminal_translates_state_error(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    """An invalid lifecycle transition surfaces as an application conflict."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    command = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    await command_app_service.mark_dispatched(command.id)
    await command_app_service.mark_running(command.id)
    await command_app_service.complete_command(command.id, result={"ok": True})
    with pytest.raises(InvalidCommandStateError):
        await command_app_service.cancel_command(command.id)


@pytest.mark.asyncio
async def test_command_service_completes_and_fails_publish_events(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
    event_bus: EventBus,
) -> None:
    """complete_command and fail_command each publish their matching domain event."""
    completed_recorder = _Recorder()
    failed_recorder = _Recorder()
    event_bus.subscribe(CommandCompleted, completed_recorder)
    event_bus.subscribe(CommandFailed, failed_recorder)
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))

    succeeding = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    await command_app_service.mark_dispatched(succeeding.id)
    await command_app_service.mark_running(succeeding.id)
    completed = await command_app_service.complete_command(succeeding.id, result={"ok": True})
    assert completed.result is not None
    assert completed.result.success is True

    failing = await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    await command_app_service.mark_dispatched(failing.id)
    await command_app_service.mark_running(failing.id)
    failed = await command_app_service.fail_command(failing.id, error_message="pump stalled")
    assert failed.result is not None
    assert failed.result.success is False

    assert len(completed_recorder.received) == 1
    assert completed_recorder.received[0].command_id == completed.id
    assert len(failed_recorder.received) == 1
    assert failed_recorder.received[0].error_message == "pump stalled"


@pytest.mark.asyncio
async def test_command_service_list_commands_validates_pagination_and_sort(
    command_app_service: CommandApplicationService,
) -> None:
    """Bad pagination and bad sort tokens are both rejected centrally."""
    with pytest.raises(ApplicationValidationError):
        await command_app_service.list_commands(
            status=None,
            device_id=None,
            priority=None,
            command_type=None,
            created_after=None,
            created_before=None,
            offset=0,
            limit=0,
            sort="-created_at",
        )
    with pytest.raises(ApplicationValidationError):
        await command_app_service.list_commands(
            status=None,
            device_id=None,
            priority=None,
            command_type=None,
            created_after=None,
            created_before=None,
            offset=0,
            limit=10,
            sort="not-a-field",
        )


@pytest.mark.asyncio
async def test_command_service_expire_old_commands_proxies_to_domain(
    command_app_service: CommandApplicationService,
    device_app_service: DeviceApplicationService,
) -> None:
    """expire_old_commands delegates straight to the domain service."""
    device = await device_app_service.register_device(DeviceCreate.model_validate(device_payload()))
    await command_app_service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    expired_count = await command_app_service.expire_old_commands()
    assert expired_count == 0


# --- SavedMediaApplicationService --------------------------------------------------


class FakeBotoClient:
    """Hand-rolled double for the boto3 S3 client slice app.core.s3_client.S3Client calls."""

    def __init__(
        self, *, presigned_url: str = "https://s3.example/signed", fail_delete: bool = False
    ) -> None:
        self.presigned_url = presigned_url
        self.fail_delete = fail_delete
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
        if self.fail_delete:
            raise RuntimeError("s3 delete failed")
        self.delete_calls.append(kwargs)
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("not exercised by these tests")


@pytest.fixture
async def seeded_media(session: AsyncSession) -> SavedMedia:
    """Persist one IMAGE row, plus the device/command rows its foreign keys require."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(device_payload())
    )
    command = await CommandRepository(session).create(
        Command(device_id=device.id, command_type="camera.snapshot", payload={})
    )
    saved_media_service = SavedMediaService(SavedMediaRepository(session))
    return await saved_media_service.record_media(
        media_type=MediaType.IMAGE,
        device_id=device.id,
        command_id=command.id,
        filename="snapshot.jpg",
        bucket="samslab-snapshots",
        original_object_key="originals/snapshot.jpg",
        thumbnail_object_key="thumbnails/snapshot.jpg",
        etag='"abc123"',
        sha256="a" * 64,
        width=1920,
        height=1080,
        size=204800,
        captured_at=datetime.now(UTC),
    )


def _saved_media_app_service(
    session: AsyncSession, *, s3_client: S3Client | None, ttl_seconds: float = 300.0
) -> SavedMediaApplicationService:
    return SavedMediaApplicationService(
        SavedMediaService(SavedMediaRepository(session)),
        s3_client=s3_client,
        presigned_url_ttl_seconds=ttl_seconds,
    )


@pytest.mark.asyncio
async def test_saved_media_service_get_media_returns_dto_with_presigned_urls(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """get_media mints one presigned URL per object key and never returns raw keys."""
    fake = FakeBotoClient(presigned_url="https://s3.example/signed")
    service = _saved_media_app_service(
        session, s3_client=S3Client(client=fake, bucket="samslab-snapshots")
    )

    dto = await service.get_media(seeded_media.id)

    assert isinstance(dto, SavedMediaDTO)
    assert dto.thumbnail_url == "https://s3.example/signed"
    assert dto.image_url == "https://s3.example/signed"
    assert {call["Params"]["Key"] for call in fake.presign_calls} == {
        "thumbnails/snapshot.jpg",
        "originals/snapshot.jpg",
    }


@pytest.mark.asyncio
async def test_saved_media_service_presigned_urls_reflect_the_injected_ttl(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """The configured presigned_url_ttl_seconds reaches boto3's ExpiresIn unchanged."""
    fake = FakeBotoClient()
    service = _saved_media_app_service(
        session, s3_client=S3Client(client=fake, bucket="b"), ttl_seconds=120.0
    )

    await service.get_media(seeded_media.id)

    assert fake.presign_calls
    assert all(call["ExpiresIn"] == 120 for call in fake.presign_calls)


@pytest.mark.asyncio
async def test_saved_media_service_get_media_urls_are_empty_when_s3_unconfigured(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """An unconfigured S3 adapter yields empty-string URLs rather than raising."""
    service = _saved_media_app_service(session, s3_client=None)

    dto = await service.get_media(seeded_media.id)

    assert dto.thumbnail_url == ""
    assert dto.image_url == ""


@pytest.mark.asyncio
async def test_saved_media_service_get_media_translates_not_found(session: AsyncSession) -> None:
    """A missing id raises the application's not-found error, not the domain's."""
    service = _saved_media_app_service(session, s3_client=None)
    with pytest.raises(SavedMediaNotFoundError):
        await service.get_media(uuid4())


@pytest.mark.asyncio
async def test_saved_media_service_list_media_returns_page_dto_with_urls(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """list_media returns a bounded page of DTOs, each carrying fresh presigned URLs."""
    fake = FakeBotoClient()
    service = _saved_media_app_service(session, s3_client=S3Client(client=fake, bucket="b"))

    page = await service.list_media(
        device_id=None, media_type=None, captured_after=None, offset=0, limit=10
    )

    assert isinstance(page, SavedMediaPageDTO)
    assert page.total == 1
    assert page.items[0].id == seeded_media.id
    assert page.items[0].thumbnail_url == fake.presigned_url


@pytest.mark.asyncio
async def test_saved_media_service_delete_media_deletes_both_s3_objects_and_the_row(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """Deleting a row removes both S3 objects and hard-deletes the metadata row."""
    fake = FakeBotoClient()
    service = _saved_media_app_service(session, s3_client=S3Client(client=fake, bucket="b"))

    await service.delete_media(seeded_media.id)

    assert {call["Key"] for call in fake.delete_calls} == {
        "originals/snapshot.jpg",
        "thumbnails/snapshot.jpg",
    }
    with pytest.raises(SavedMediaNotFoundError):
        await service.get_media(seeded_media.id)


@pytest.mark.asyncio
async def test_saved_media_service_delete_media_survives_an_s3_delete_failure(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """An S3 delete failure is swallowed (logged) and never blocks the row's deletion."""
    fake = FakeBotoClient(fail_delete=True)
    service = _saved_media_app_service(session, s3_client=S3Client(client=fake, bucket="b"))

    await service.delete_media(seeded_media.id)

    with pytest.raises(SavedMediaNotFoundError):
        await service.get_media(seeded_media.id)


@pytest.mark.asyncio
async def test_saved_media_service_delete_media_works_when_s3_is_unconfigured(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """No S3 adapter at all is likewise never a blocker for deleting the metadata row."""
    service = _saved_media_app_service(session, s3_client=None)

    await service.delete_media(seeded_media.id)

    with pytest.raises(SavedMediaNotFoundError):
        await service.get_media(seeded_media.id)


@pytest.mark.asyncio
async def test_saved_media_service_delete_media_translates_not_found(session: AsyncSession) -> None:
    """Deleting a missing id raises the application's not-found error."""
    service = _saved_media_app_service(session, s3_client=None)
    with pytest.raises(SavedMediaNotFoundError):
        await service.delete_media(uuid4())


@pytest.mark.asyncio
async def test_saved_media_service_delete_media_skips_a_missing_thumbnail_key(
    session: AsyncSession,
) -> None:
    """A VIDEO row's null thumbnail_object_key is never passed to delete_object."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(device_payload())
    )
    command = await CommandRepository(session).create(
        Command(device_id=device.id, command_type="camera.record.stop", payload={})
    )
    video = await SavedMediaService(SavedMediaRepository(session)).record_media(
        media_type=MediaType.VIDEO,
        device_id=device.id,
        command_id=command.id,
        filename="recording.mp4",
        bucket="samslab-videos",
        original_object_key="videos/recording.mp4",
        thumbnail_object_key=None,
        etag='"abc123"',
        sha256="a" * 64,
        width=1920,
        height=1080,
        duration=60,
        fps=30,
        bitrate=8000,
        size=1_048_576,
        captured_at=datetime.now(UTC),
    )
    fake = FakeBotoClient()
    service = _saved_media_app_service(session, s3_client=S3Client(client=fake, bucket="b"))

    await service.delete_media(video.id)

    assert {call["Key"] for call in fake.delete_calls} == {"videos/recording.mp4"}


@pytest.mark.asyncio
async def test_saved_media_service_get_media_resolves_workflow_name_when_present(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """A workflow-linked row's DTO carries the originating workflow's current name."""
    workflow_service = WorkflowService(WorkflowRepository(session))
    workflow = await workflow_service.register_workflow(WorkflowCreate(name="Nightly patrol"))
    second_command = await CommandRepository(session).create(
        Command(device_id=seeded_media.device_id, command_type="camera.snapshot", payload={})
    )
    await SavedMediaService(SavedMediaRepository(session)).record_media(
        media_type=MediaType.IMAGE,
        device_id=seeded_media.device_id,
        command_id=second_command.id,
        filename="linked.jpg",
        bucket="samslab-snapshots",
        original_object_key="originals/linked.jpg",
        thumbnail_object_key="thumbnails/linked.jpg",
        etag='"def456"',
        sha256="b" * 64,
        width=1920,
        height=1080,
        size=204800,
        captured_at=datetime.now(UTC),
        workflow_id=workflow.id,
        workflow_run_id=uuid4(),
    )
    service = SavedMediaApplicationService(
        SavedMediaService(SavedMediaRepository(session)),
        s3_client=None,
        presigned_url_ttl_seconds=300.0,
        workflow_service=workflow_service,
    )

    page = await service.list_media(
        device_id=None, media_type=None, captured_after=None, offset=0, limit=10
    )

    linked = next(item for item in page.items if item.filename == "linked.jpg")
    assert linked.workflow_id == workflow.id
    assert linked.workflow_name == "Nightly patrol"
    unlinked = next(item for item in page.items if item.id == seeded_media.id)
    assert unlinked.workflow_id is None
    assert unlinked.workflow_name is None


@pytest.mark.asyncio
async def test_saved_media_service_workflow_name_is_none_without_a_workflow_service(
    session: AsyncSession,
) -> None:
    """Omitting workflow_service (the delete-cascade path) never resolves a name."""
    workflow_service = WorkflowService(WorkflowRepository(session))
    workflow = await workflow_service.register_workflow(WorkflowCreate(name="Nightly patrol"))
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(device_payload())
    )
    command = await CommandRepository(session).create(
        Command(device_id=device.id, command_type="camera.snapshot", payload={})
    )
    await SavedMediaService(SavedMediaRepository(session)).record_media(
        media_type=MediaType.IMAGE,
        device_id=device.id,
        command_id=command.id,
        filename="linked.jpg",
        bucket="samslab-snapshots",
        original_object_key="originals/linked.jpg",
        thumbnail_object_key="thumbnails/linked.jpg",
        etag='"def456"',
        sha256="b" * 64,
        width=1920,
        height=1080,
        size=204800,
        captured_at=datetime.now(UTC),
        workflow_id=workflow.id,
        workflow_run_id=uuid4(),
    )
    service = _saved_media_app_service(session, s3_client=None)

    dto = await service.list_media(
        device_id=None, media_type=None, captured_after=None, offset=0, limit=10
    )

    assert dto.items[0].workflow_id == workflow.id
    assert dto.items[0].workflow_name is None


@pytest.mark.asyncio
async def test_saved_media_service_delete_media_translates_a_race_after_the_initial_lookup(
    session: AsyncSession, seeded_media: SavedMedia
) -> None:
    """delete_media's own second try/except (post-S3-cleanup) is reached via a stubbed
    domain service — the real domain delete_media can't itself raise once get_media
    already found the row, so this proves the translation still fires if a future
    concurrent-delete race ever does trigger it, mirroring _FailingCommandService above."""

    class _FailingSavedMediaService(SavedMediaService):
        async def delete_media(self, media_id: UUID) -> SavedMedia:
            raise SavedMediaNotFound("simulated concurrent delete")

    stub_service = SavedMediaApplicationService(
        _FailingSavedMediaService(SavedMediaRepository(session)),
        s3_client=None,
        presigned_url_ttl_seconds=300.0,
    )
    with pytest.raises(SavedMediaNotFoundError):
        await stub_service.delete_media(seeded_media.id)


# --- HealthApplicationService --------------------------------------------------


def test_health_service_describes_configured_service_name() -> None:
    """The identity use case reports the configured server name."""
    service = HealthApplicationService("Sam's Lab Test Server")
    info = service.describe_service()
    assert info.service == "Sam's Lab Test Server"
    assert info.status == "ok"


def test_health_service_reports_ok_for_every_probe() -> None:
    """Health, readiness, and liveness all report ok with no dependency checks."""
    service = HealthApplicationService("Sam's Lab Test Server")
    assert service.check_health().status == "ok"
    assert service.check_readiness().status == "ok"
    assert service.check_liveness().status == "ok"
