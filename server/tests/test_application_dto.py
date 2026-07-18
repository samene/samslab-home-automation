"""Tests for application DTOs and their mappers, and domain-error translation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.application.dto.camera_dto import CameraSnapshotDTO
from app.application.dto.command_dto import CommandDTO
from app.application.dto.device_dto import CapabilityDTO, DeviceDTO
from app.application.exceptions import (
    ApplicationError,
    CommandNotFoundError,
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DuplicateCapabilityError,
    InvalidCommandStateError,
    InvalidHeartbeatError,
    SnapshotNotFoundError,
    translate_domain_error,
)
from app.application.mappers.command_mapper import (
    to_command_detail_dto,
    to_command_dto,
    to_command_event_dto,
    to_command_result_dto,
)
from app.application.mappers.device_mapper import to_capability_dto, to_device_dto
from app.application.mappers.snapshot_mapper import to_camera_snapshot_dto, to_snapshot_dto
from app.domains.commands.events import CommandEventType
from app.domains.commands.exceptions import CommandNotFound, InvalidStateTransition
from app.domains.commands.models import (
    Command,
    CommandEvent,
    CommandPriority,
    CommandResult,
    CommandStatus,
)
from app.domains.devices.exceptions import (
    DeviceAlreadyExists,
    DeviceNotFound,
    DuplicateCapability,
    InvalidHeartbeat,
)
from app.domains.devices.models import Device, DeviceCapability, DeviceStatus
from app.domains.snapshots.exceptions import SnapshotNotFound
from app.domains.snapshots.models import Snapshot


def test_dtos_construct_independently_of_any_orm_model() -> None:
    """A DTO is a plain, constructible Pydantic model with no ORM dependency."""
    capability = CapabilityDTO(id=uuid4(), capability="gpio", version="1.0", configuration={})
    device = DeviceDTO(
        id=uuid4(),
        device_name="garden-node",
        hostname="garden-node.local",
        display_name="Garden node",
        description=None,
        status=DeviceStatus.REGISTERING,
        last_seen=None,
        agent_version=None,
        protocol_version=None,
        registered_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        enabled=True,
        metadata={},
        capabilities=[capability],
    )
    assert device.capabilities == [capability]


def test_device_mapper_translates_persisted_device_fields() -> None:
    """to_device_dto maps every field, including the metadata_/metadata rename."""
    capability = DeviceCapability(
        id=uuid4(), capability="gpio", version="1.0", configuration={"pin": 4}
    )
    device = Device(
        id=uuid4(),
        device_name="garden-node",
        hostname="garden-node.local",
        display_name="Garden node",
        description="A garden controller",
        status=DeviceStatus.ONLINE,
        registered_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        enabled=True,
        metadata_={"site": "home"},
        capabilities=[capability],
    )

    dto = to_device_dto(device)

    assert dto.device_name == "garden-node"
    assert dto.metadata == {"site": "home"}
    assert dto.capabilities == [to_capability_dto(capability)]
    assert dto.capabilities[0].configuration == {"pin": 4}


def test_command_mapper_translates_persisted_command_without_result_or_events() -> None:
    """to_command_dto maps a command's own fields, independent of its result/events."""
    command = Command(
        id=uuid4(),
        device_id=uuid4(),
        command_type="pump.start",
        status=CommandStatus.PENDING,
        priority=CommandPriority.HIGH,
        payload={"duration_s": 30},
        created_at=datetime.now(UTC),
        correlation_id=uuid4(),
        retry_count=0,
        max_retries=0,
    )

    dto = to_command_dto(command)

    assert isinstance(dto, CommandDTO)
    assert dto.command_type == "pump.start"
    assert dto.priority is CommandPriority.HIGH


def test_command_mapper_translates_result_and_event_trail() -> None:
    """to_command_detail_dto nests the mapped result and the full ordered event trail."""
    command = Command(
        id=uuid4(),
        device_id=uuid4(),
        command_type="pump.start",
        status=CommandStatus.COMPLETED,
        priority=CommandPriority.NORMAL,
        payload={},
        created_at=datetime.now(UTC),
        correlation_id=uuid4(),
        retry_count=0,
        max_retries=0,
    )
    command.result = CommandResult(
        id=uuid4(),
        success=True,
        exit_code=0,
        result={"ok": True},
        error_message=None,
        duration_ms=10,
        completed_at=datetime.now(UTC),
    )
    command.events = [
        CommandEvent(
            id=uuid4(),
            event_type=CommandEventType.COMMAND_CREATED,
            timestamp=datetime.now(UTC),
            details={},
        )
    ]

    detail = to_command_detail_dto(command)

    assert detail.result == to_command_result_dto(command.result)
    assert detail.events == [to_command_event_dto(event) for event in command.events]


def test_command_mapper_detail_dto_has_no_result_when_command_is_unfinished() -> None:
    """A command with no stored result maps to result=None, not a missing field."""
    command = Command(
        id=uuid4(),
        device_id=uuid4(),
        command_type="pump.start",
        status=CommandStatus.PENDING,
        priority=CommandPriority.NORMAL,
        payload={},
        created_at=datetime.now(UTC),
        correlation_id=uuid4(),
        retry_count=0,
        max_retries=0,
    )
    command.events = []

    detail = to_command_detail_dto(command)

    assert detail.result is None
    assert detail.events == []


def test_translate_domain_error_maps_every_known_domain_exception() -> None:
    """Every domain exception this application depends on has an explicit translation."""
    assert isinstance(translate_domain_error(DeviceAlreadyExists("x")), DeviceAlreadyExistsError)
    assert isinstance(translate_domain_error(DeviceNotFound("x")), DeviceNotFoundError)
    assert isinstance(translate_domain_error(DuplicateCapability("x")), DuplicateCapabilityError)
    assert isinstance(translate_domain_error(InvalidHeartbeat("x")), InvalidHeartbeatError)
    assert isinstance(translate_domain_error(CommandNotFound("x")), CommandNotFoundError)
    assert isinstance(translate_domain_error(InvalidStateTransition("x")), InvalidCommandStateError)
    assert isinstance(translate_domain_error(SnapshotNotFound("x")), SnapshotNotFoundError)


def _build_snapshot(**overrides: object) -> Snapshot:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "device_id": uuid4(),
        "command_id": uuid4(),
        "filename": "snapshot.jpg",
        "bucket": "samslab-snapshots",
        "original_object_key": "originals/snapshot.jpg",
        "thumbnail_object_key": "thumbnails/snapshot.jpg",
        "etag": "\"abc123\"",
        "sha256": "a" * 64,
        "width": 1920,
        "height": 1080,
        "size": 204800,
        "captured_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "metadata_": {},
    }
    defaults.update(overrides)
    return Snapshot(**defaults)


def test_snapshot_mapper_attaches_freshly_minted_presigned_urls() -> None:
    """to_snapshot_dto maps persisted fields and attaches the caller-supplied URLs verbatim."""
    snapshot = _build_snapshot()

    dto = to_snapshot_dto(
        snapshot,
        thumbnail_url="https://s3.example/thumb?sig=1",
        image_url="https://s3.example/full?sig=2",
    )

    assert dto.id == snapshot.id
    assert dto.filename == "snapshot.jpg"
    assert dto.thumbnail_url == "https://s3.example/thumb?sig=1"
    assert dto.image_url == "https://s3.example/full?sig=2"
    assert dto.metadata == {}


def test_camera_snapshot_mapper_exposes_metadata_only_no_urls_or_bucket() -> None:
    """to_camera_snapshot_dto never leaks S3 URLs, object keys, or the bucket name."""
    snapshot = _build_snapshot()

    dto = to_camera_snapshot_dto(snapshot)

    assert isinstance(dto, CameraSnapshotDTO)
    assert dto.id == snapshot.id
    assert dto.device_id == snapshot.device_id
    assert dto.command_id == snapshot.command_id
    assert dto.filename == snapshot.filename
    assert dto.width == snapshot.width
    assert dto.height == snapshot.height
    assert dto.size == snapshot.size
    assert dto.captured_at == snapshot.captured_at
    dumped = dto.model_dump()
    assert "thumbnail_url" not in dumped
    assert "image_url" not in dumped
    assert "bucket" not in dumped
    assert "original_object_key" not in dumped
    assert "thumbnail_object_key" not in dumped


def test_translate_domain_error_falls_back_to_generic_application_error() -> None:
    """An unmapped domain exception still yields a safe, generic ApplicationError."""

    class _SomeOtherDomainError(Exception):
        pass

    translated = translate_domain_error(_SomeOtherDomainError("unexpected"))
    assert type(translated) is ApplicationError
    assert str(translated) == "unexpected"
