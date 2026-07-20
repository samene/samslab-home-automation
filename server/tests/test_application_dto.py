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
    SavedMediaNotFoundError,
    translate_domain_error,
)
from app.application.mappers.command_mapper import (
    to_command_detail_dto,
    to_command_dto,
    to_command_event_dto,
    to_command_result_dto,
)
from app.application.mappers.device_mapper import to_capability_dto, to_device_dto
from app.application.mappers.saved_media_mapper import to_camera_snapshot_dto, to_saved_media_dto
from app.application.mappers.workflow_mapper import (
    to_step_tree,
    to_workflow_detail_dto,
    to_workflow_dto,
    to_workflow_run_dto,
)
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
from app.domains.saved_media.exceptions import SavedMediaNotFound
from app.domains.saved_media.models import MediaType, SavedMedia
from app.domains.workflows.models import (
    Workflow,
    WorkflowGroupMode,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStep,
    WorkflowStepRun,
    WorkflowStepRunStatus,
    WorkflowStepType,
)


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
    assert isinstance(translate_domain_error(SavedMediaNotFound("x")), SavedMediaNotFoundError)


def _build_media(**overrides: object) -> SavedMedia:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "media_type": MediaType.IMAGE,
        "device_id": uuid4(),
        "command_id": uuid4(),
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
        "created_at": datetime.now(UTC),
        "metadata_": {},
    }
    defaults.update(overrides)
    return SavedMedia(**defaults)


def test_saved_media_mapper_attaches_freshly_minted_presigned_urls() -> None:
    """to_saved_media_dto maps persisted fields and attaches the caller-supplied URLs verbatim."""
    media = _build_media()

    dto = to_saved_media_dto(
        media,
        thumbnail_url="https://s3.example/thumb?sig=1",
        media_url="https://s3.example/full?sig=2",
    )

    assert dto.id == media.id
    assert dto.filename == "snapshot.jpg"
    assert dto.thumbnail_url == "https://s3.example/thumb?sig=1"
    assert dto.image_url == "https://s3.example/full?sig=2"
    assert dto.video_url == ""
    assert dto.metadata == {}


def test_camera_snapshot_mapper_exposes_metadata_only_no_urls_or_bucket() -> None:
    """to_camera_snapshot_dto never leaks S3 URLs, object keys, or the bucket name."""
    media = _build_media()

    dto = to_camera_snapshot_dto(media)

    assert isinstance(dto, CameraSnapshotDTO)
    assert dto.id == media.id
    assert dto.device_id == media.device_id
    assert dto.command_id == media.command_id
    assert dto.filename == media.filename
    assert dto.width == media.width
    assert dto.height == media.height
    assert dto.size == media.size
    assert dto.captured_at == media.captured_at
    dumped = dto.model_dump()
    assert "thumbnail_url" not in dumped
    assert "image_url" not in dumped
    assert "bucket" not in dumped
    assert "original_object_key" not in dumped
    assert "thumbnail_object_key" not in dumped


def _step(
    *,
    workflow_id: object,
    parent_step_id: object = None,
    position: int = 0,
    step_type: WorkflowStepType = WorkflowStepType.SLEEP,
    command_type: str | None = None,
    sleep_seconds: int | None = 5,
    group_mode: WorkflowGroupMode | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        id=uuid4(),
        workflow_id=workflow_id,
        parent_step_id=parent_step_id,
        position=position,
        step_type=step_type,
        command_type=command_type,
        sleep_seconds=sleep_seconds,
        group_mode=group_mode,
    )


def test_to_step_tree_rebuilds_nesting_from_a_flat_list() -> None:
    """A GROUP step's children are reassembled purely from parent_step_id, not an ORM relationship."""
    workflow_id = uuid4()
    root_command = _step(
        workflow_id=workflow_id,
        position=0,
        step_type=WorkflowStepType.COMMAND,
        command_type="camera.snapshot",
        sleep_seconds=None,
    )
    group = _step(
        workflow_id=workflow_id,
        position=1,
        step_type=WorkflowStepType.GROUP,
        sleep_seconds=None,
        group_mode=WorkflowGroupMode.PARALLEL,
    )
    child_a = _step(workflow_id=workflow_id, parent_step_id=group.id, position=0)
    child_b = _step(workflow_id=workflow_id, parent_step_id=group.id, position=1)

    tree = to_step_tree([child_b, group, root_command, child_a])  # deliberately out of order

    assert [node.step_type for node in tree] == [WorkflowStepType.COMMAND, WorkflowStepType.GROUP]
    assert tree[0].children == []
    assert [child.id for child in tree[1].children] == [child_a.id, child_b.id]


def test_workflow_step_dto_recursive_round_trip() -> None:
    """The first self-referential Pydantic model in this codebase: verify it actually round-trips."""
    workflow_id = uuid4()
    group = _step(
        workflow_id=workflow_id,
        position=0,
        step_type=WorkflowStepType.GROUP,
        sleep_seconds=None,
        group_mode=WorkflowGroupMode.SERIAL,
    )
    nested_group = _step(
        workflow_id=workflow_id,
        parent_step_id=group.id,
        position=0,
        step_type=WorkflowStepType.GROUP,
        sleep_seconds=None,
        group_mode=WorkflowGroupMode.PARALLEL,
    )
    leaf_a = _step(workflow_id=workflow_id, parent_step_id=nested_group.id, position=0)
    leaf_b = _step(workflow_id=workflow_id, parent_step_id=nested_group.id, position=1)

    tree = to_step_tree([group, nested_group, leaf_a, leaf_b])
    dumped = [node.model_dump() for node in tree]
    rebuilt = [type(tree[0]).model_validate(item) for item in dumped]

    assert rebuilt == tree
    assert rebuilt[0].children[0].children[0].id == leaf_a.id


def test_workflow_step_dto_round_trip_handles_a_deeper_branching_tree() -> None:
    """One level deeper than the recursive round-trip test above, and branching.

    The existing round-trip test only ever chains a single child per node
    (GROUP -> GROUP -> leaf, leaf). This tree adds a sibling leaf alongside a
    nested GROUP at the root, and nests a third GROUP below that — a shape
    the recursive `to_step_tree`/DTO round-trip must still handle correctly.
    """
    workflow_id = uuid4()
    root_group = _step(
        workflow_id=workflow_id,
        position=0,
        step_type=WorkflowStepType.GROUP,
        sleep_seconds=None,
        group_mode=WorkflowGroupMode.SERIAL,
    )
    sibling_leaf = _step(
        workflow_id=workflow_id,
        parent_step_id=root_group.id,
        position=0,
        step_type=WorkflowStepType.COMMAND,
        command_type="camera.snapshot",
        sleep_seconds=None,
    )
    mid_group = _step(
        workflow_id=workflow_id,
        parent_step_id=root_group.id,
        position=1,
        step_type=WorkflowStepType.GROUP,
        sleep_seconds=None,
        group_mode=WorkflowGroupMode.PARALLEL,
    )
    inner_group = _step(
        workflow_id=workflow_id,
        parent_step_id=mid_group.id,
        position=0,
        step_type=WorkflowStepType.GROUP,
        sleep_seconds=None,
        group_mode=WorkflowGroupMode.SERIAL,
    )
    leaf_a = _step(workflow_id=workflow_id, parent_step_id=inner_group.id, position=0)
    leaf_b = _step(workflow_id=workflow_id, parent_step_id=inner_group.id, position=1)

    tree = to_step_tree([root_group, sibling_leaf, mid_group, inner_group, leaf_a, leaf_b])
    dumped = [node.model_dump() for node in tree]
    rebuilt = [type(tree[0]).model_validate(item) for item in dumped]

    assert rebuilt == tree
    assert rebuilt[0].children[0].step_type == WorkflowStepType.COMMAND
    assert rebuilt[0].children[1].children[0].children[0].id == leaf_a.id
    assert rebuilt[0].children[1].children[0].children[1].id == leaf_b.id


def test_to_workflow_run_dto_fills_pending_placeholders_for_unstarted_steps() -> None:
    """A step with no matching WorkflowStepRun row yet still appears, as PENDING."""
    workflow_id = uuid4()
    run_id = uuid4()
    first = _step(workflow_id=workflow_id, position=0, sleep_seconds=1)
    second = _step(workflow_id=workflow_id, position=1, sleep_seconds=2)
    completed_run = WorkflowStepRun(
        id=uuid4(),
        workflow_run_id=run_id,
        workflow_step_id=first.id,
        status=WorkflowStepRunStatus.COMPLETED,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )
    run = WorkflowRun(
        id=run_id,
        workflow_id=workflow_id,
        status=WorkflowRunStatus.RUNNING,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    dto = to_workflow_run_dto(run, [first, second], [completed_run])

    assert dto.step_runs[0].status == WorkflowStepRunStatus.COMPLETED
    assert dto.step_runs[1].status == WorkflowStepRunStatus.PENDING
    assert dto.step_runs[1].id is None
    assert dto.step_runs[1].workflow_step_id == second.id


def test_to_workflow_detail_dto_embeds_the_latest_run() -> None:
    workflow_id = uuid4()
    workflow = Workflow(
        id=workflow_id,
        name="Nightly",
        description=None,
        enabled=True,
        run_count=1,
        last_run_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_run_status=WorkflowRunStatus.COMPLETED,
        last_run_duration_ms=1200,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    step = _step(workflow_id=workflow_id, position=0)
    run = WorkflowRun(
        id=uuid4(),
        workflow_id=workflow_id,
        status=WorkflowRunStatus.COMPLETED,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    dto = to_workflow_detail_dto(workflow, [step], latest_run=run, latest_run_step_runs=[])

    assert dto.name == "Nightly"
    assert len(dto.steps) == 1
    assert dto.latest_run is not None
    assert dto.latest_run.id == run.id


def test_to_workflow_detail_dto_latest_run_is_none_when_never_run() -> None:
    workflow = Workflow(
        id=uuid4(),
        name="Never run",
        description=None,
        enabled=True,
        run_count=0,
        last_run_at=None,
        last_run_status=None,
        last_run_duration_ms=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    dto = to_workflow_detail_dto(workflow, [], latest_run=None, latest_run_step_runs=[])

    assert dto.latest_run is None
    assert dto.steps == []


def test_to_workflow_dto_maps_denormalized_fields() -> None:
    workflow = Workflow(
        id=uuid4(),
        name="Backup",
        description="desc",
        enabled=False,
        run_count=3,
        last_run_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_run_status=WorkflowRunStatus.FAILED,
        last_run_duration_ms=500,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    dto = to_workflow_dto(workflow)

    assert dto.enabled is False
    assert dto.run_count == 3
    assert dto.last_run_status == WorkflowRunStatus.FAILED


def test_translate_domain_error_falls_back_to_generic_application_error() -> None:
    """An unmapped domain exception still yields a safe, generic ApplicationError."""

    class _SomeOtherDomainError(Exception):
        pass

    translated = translate_domain_error(_SomeOtherDomainError("unexpected"))
    assert type(translated) is ApplicationError
    assert str(translated) == "unexpected"
