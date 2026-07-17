"""Tests for application services: cross-domain orchestration, DTOs, and event publishing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.command_dto import CommandDetailDTO
from app.application.dto.device_dto import CapabilityDTO, DeviceDTO
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
)
from app.application.services.command_service import CommandApplicationService
from app.application.services.device_service import DeviceApplicationService
from app.application.services.health_service import HealthApplicationService
from app.core.database import Database
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
