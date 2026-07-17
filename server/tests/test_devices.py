"""Repository, service, API, migration-metadata, and validation tests for Device Registry."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.devices.exceptions import (
    DeviceAlreadyExists,
    DeviceNotFound,
    DuplicateCapability,
    InvalidHeartbeat,
)
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import (
    CapabilityInput,
    CapabilityReplace,
    DeviceCreate,
    DeviceUpdate,
    HeartbeatInput,
)
from app.domains.devices.service import DeviceService
from app.main import create_app


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database for each domain test."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'devices.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def service(database: Database) -> AsyncIterator[DeviceService]:
    """Provide a transaction-scoped service for repository/service tests."""
    async with database.session_factory() as session:
        yield DeviceService(DeviceRepository(session))
        try:
            await session.commit()
        except Exception:
            # A test may have already asserted on and swallowed a DB-level
            # failure (e.g. a raw IntegrityError), leaving the transaction
            # unusable; there is nothing further for teardown to commit.
            await session.rollback()


@pytest.fixture
async def repository(database: Database) -> AsyncIterator[DeviceRepository]:
    """Provide a transaction-scoped repository for persistence-only tests."""
    async with database.session_factory() as session:
        yield DeviceRepository(session)
        try:
            await session.commit()
        except Exception:
            await session.rollback()


def device_payload(name: str = "garden-node") -> dict[str, object]:
    """Create a valid extensible device payload without assuming a hardware type."""
    return {
        "device_name": name,
        "hostname": f"{name}.local",
        "display_name": "Garden node",
        "metadata": {"site": "home"},
        "capabilities": [
            {"capability": "gpio", "version": "1.0"},
            {"capability": "soil_sensor", "version": "2.0", "configuration": {"channel": 1}},
        ],
    }


def build_device(name: str = "garden-node") -> Device:
    """Build a transient Device model for repository-only persistence tests."""
    return Device(
        device_name=name,
        hostname=f"{name}.local",
        display_name="Garden node",
        metadata_={"site": "home"},
        status=DeviceStatus.REGISTERING,
    )


# --- Repository -------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_finds_by_id_and_name(repository: DeviceRepository) -> None:
    """A created device is retrievable by both its UUID and its unique name."""
    device = await repository.create(build_device())
    device = await repository.replace_capabilities(
        device, [CapabilityInput(capability="gpio", version="1.0")]
    )

    found_by_id = await repository.find_by_id(device.id)
    assert found_by_id is not None
    assert found_by_id.id == device.id
    assert (await repository.find_by_name("garden-node")) is not None
    assert (await repository.find_by_name("missing-node")) is None


@pytest.mark.asyncio
async def test_repository_soft_delete_excludes_device_from_queries(
    repository: DeviceRepository,
) -> None:
    """A soft-deleted device disappears from lookups but the row is never dropped."""
    device = await repository.create(build_device())
    await repository.delete(device)

    assert (await repository.find_by_id(device.id)) is None
    assert (await repository.find_by_name("garden-node")) is None
    devices, total = await repository.find_all(
        status=None, enabled=None, capability=None, search=None, offset=0, limit=10
    )
    assert devices == []
    assert total == 0


@pytest.mark.asyncio
async def test_repository_find_all_paginates_bounded_results(
    repository: DeviceRepository,
) -> None:
    """Pagination bounds the page size while total reflects the full matching count."""
    for index in range(3):
        await repository.create(build_device(f"node-{index}"))

    page, total = await repository.find_all(
        status=None, enabled=None, capability=None, search=None, offset=1, limit=1
    )
    assert total == 3
    assert len(page) == 1


@pytest.mark.asyncio
async def test_repository_rejects_duplicate_capability_rows(
    repository: DeviceRepository,
) -> None:
    """The database-level unique constraint backstops capability uniqueness."""
    device = await repository.create(build_device())
    with pytest.raises(IntegrityError):
        await repository.replace_capabilities(
            device,
            [
                CapabilityInput(capability="gpio", version="1"),
                CapabilityInput(capability="gpio", version="2"),
            ],
        )


class _StaleUniquenessRepository(DeviceRepository):
    """A repository stub whose uniqueness checks never see a concurrent writer's rows."""

    async def find_by_name(self, device_name: str) -> Device | None:
        return None


class _RacingCapabilitiesRepository(DeviceRepository):
    """A repository stub whose second capability replacement simulates a DB-level race."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._raise_next = False

    async def replace_capabilities(
        self, device: Device, capabilities: list[CapabilityInput]
    ) -> Device:
        if self._raise_next:
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        self._raise_next = True
        return await super().replace_capabilities(device, capabilities)


# --- Service -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_registers_filters_heartbeats_and_soft_deletes(
    service: DeviceService,
) -> None:
    """The service owns lifecycle rules while the repository persists the effects."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    assert device.status is DeviceStatus.REGISTERING
    assert len(device.capabilities) == 2

    heartbeat = await service.heartbeat(
        device.id,
        HeartbeatInput(status=DeviceStatus.ONLINE, agent_version="1.2.3", protocol_version="1.0"),
    )
    assert heartbeat.last_seen is not None
    assert heartbeat.status is DeviceStatus.ONLINE
    assert heartbeat.agent_version == "1.2.3"
    assert heartbeat.updated_at is not None

    listed, total = await service.list_devices(
        status=DeviceStatus.ONLINE,
        enabled=True,
        capability="soil_sensor",
        search="Garden",
        offset=0,
        limit=10,
    )
    assert total == 1
    assert [item.id for item in listed] == [device.id]

    await service.delete(device.id)
    with pytest.raises(DeviceNotFound):
        await service.get_device(device.id)


@pytest.mark.asyncio
async def test_service_enforces_uniqueness_and_heartbeat_safety(service: DeviceService) -> None:
    """Duplicate names and disabled-device heartbeats yield explicit domain failures."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    with pytest.raises(DeviceAlreadyExists):
        await service.register_device(DeviceCreate.model_validate(device_payload()))
    await service.disable(device.id)
    with pytest.raises(InvalidHeartbeat):
        await service.heartbeat(
            device.id,
            HeartbeatInput(status=DeviceStatus.ONLINE, agent_version="1", protocol_version="1"),
        )


@pytest.mark.asyncio
async def test_service_maps_concurrent_registration_race_to_domain_error(
    database: Database,
) -> None:
    """A racing writer that slips past a stale uniqueness check still yields a safe 409."""
    async with database.session_factory() as session:
        service = DeviceService(_StaleUniquenessRepository(session))
        await service.register_device(DeviceCreate.model_validate(device_payload()))
        with pytest.raises(DeviceAlreadyExists):
            await service.register_device(DeviceCreate.model_validate(device_payload()))
        await session.rollback()


@pytest.mark.asyncio
async def test_service_rejects_heartbeat_status_disabled(service: DeviceService) -> None:
    """A heartbeat can never itself set a device's status to DISABLED."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    with pytest.raises(InvalidHeartbeat):
        await service.heartbeat(
            device.id,
            HeartbeatInput(
                status=DeviceStatus.DISABLED, agent_version="1.0", protocol_version="1.0"
            ),
        )


@pytest.mark.asyncio
async def test_service_enable_returns_device_to_unknown_state(service: DeviceService) -> None:
    """Re-enabling a device clears its disabled status until the next heartbeat."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    await service.disable(device.id)
    enabled = await service.enable(device.id)
    assert enabled.enabled is True
    assert enabled.status is DeviceStatus.UNKNOWN


@pytest.mark.asyncio
async def test_service_updates_administrative_fields_only(service: DeviceService) -> None:
    """Updating a device changes only the requested administrative fields."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    updated = await service.update_device(
        device.id,
        DeviceUpdate(display_name="Greenhouse node", metadata={"site": "greenhouse"}),
    )
    assert updated.display_name == "Greenhouse node"
    assert updated.metadata_ == {"site": "greenhouse"}
    assert updated.hostname == device.hostname
    assert updated.status is DeviceStatus.REGISTERING


@pytest.mark.asyncio
async def test_service_get_and_list_raise_not_found_for_missing_device(
    service: DeviceService,
) -> None:
    """Operating on an unknown device UUID raises the domain not-found error."""
    with pytest.raises(DeviceNotFound):
        await service.get_device(uuid4())
    with pytest.raises(DeviceNotFound):
        await service.update_device(uuid4(), DeviceUpdate())
    with pytest.raises(DeviceNotFound):
        await service.delete(uuid4())


@pytest.mark.asyncio
async def test_capability_replacement_is_complete_and_atomic(service: DeviceService) -> None:
    """Replacing capabilities removes stale declarations and keeps only the requested set."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    updated = await service.replace_capabilities(
        device.id,
        CapabilityReplace.model_validate(
            {"capabilities": [{"capability": "camera", "version": "3.0"}]}
        ).capabilities,
    )
    assert [(item.capability, item.version) for item in updated.capabilities] == [("camera", "3.0")]


@pytest.mark.asyncio
async def test_capability_replacement_keeps_an_overlapping_capability_name(
    service: DeviceService,
) -> None:
    """Re-declaring a capability name the device already had must not look like a conflict."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    updated = await service.replace_capabilities(
        device.id,
        [
            CapabilityInput(capability="gpio", version="2.0"),
            CapabilityInput(capability="camera", version="1.0"),
        ],
    )
    assert sorted((item.capability, item.version) for item in updated.capabilities) == [
        ("camera", "1.0"),
        ("gpio", "2.0"),
    ]


@pytest.mark.asyncio
async def test_capability_replacement_rejects_duplicates_before_persistence(
    service: DeviceService,
) -> None:
    """The service defends against duplicate capabilities even bypassing schema validation."""
    device = await service.register_device(DeviceCreate.model_validate(device_payload()))
    with pytest.raises(DuplicateCapability):
        await service.replace_capabilities(
            device.id,
            [
                CapabilityInput(capability="gpio", version="1"),
                CapabilityInput(capability="gpio", version="2"),
            ],
        )


@pytest.mark.asyncio
async def test_service_maps_concurrent_capability_replacement_race_to_domain_error(
    database: Database,
) -> None:
    """A racing capability write that violates the DB constraint yields a safe 409."""
    async with database.session_factory() as session:
        service = DeviceService(_RacingCapabilitiesRepository(session))
        device = await service.register_device(DeviceCreate.model_validate(device_payload()))
        with pytest.raises(DuplicateCapability):
            await service.replace_capabilities(
                device.id, [CapabilityInput(capability="camera", version="1.0")]
            )
        await session.rollback()


def test_validation_rejects_invalid_names_and_duplicate_capabilities() -> None:
    """Pydantic validation protects portable device and capability identifiers."""
    invalid = device_payload()
    invalid["device_name"] = "Not Valid"
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate(invalid)
    with pytest.raises(ValidationError, match="duplicates"):
        CapabilityReplace.model_validate(
            {
                "capabilities": [
                    {"capability": "gpio", "version": "1"},
                    {"capability": "gpio", "version": "2"},
                ]
            }
        )


def test_registration_rejects_duplicate_capabilities_in_the_initial_payload() -> None:
    """A registration request is rejected just as early for duplicate capabilities."""
    invalid = device_payload()
    invalid["capabilities"] = [
        {"capability": "gpio", "version": "1"},
        {"capability": "gpio", "version": "2"},
    ]
    with pytest.raises(ValidationError, match="duplicates"):
        DeviceCreate.model_validate(invalid)


def test_device_update_accepts_and_normalizes_a_valid_hostname() -> None:
    """A well-formed hostname on an update is accepted and lower-cased like registration."""
    update = DeviceUpdate(hostname="Garden-Node.LOCAL")
    assert update.hostname == "garden-node.local"
    assert DeviceUpdate().hostname is None


def test_validation_rejects_invalid_hostnames_and_versions() -> None:
    """Hostname and version fields must match their portable identifier patterns."""
    invalid_hostname = device_payload()
    invalid_hostname["hostname"] = "not a hostname!"
    with pytest.raises(ValidationError, match="hostname"):
        DeviceCreate.model_validate(invalid_hostname)

    invalid_capability_version = device_payload()
    invalid_capability_version["capabilities"] = [{"capability": "gpio", "version": "bad version"}]
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate(invalid_capability_version)

    with pytest.raises(ValidationError):
        HeartbeatInput(
            status=DeviceStatus.ONLINE, agent_version="bad version", protocol_version="1"
        )

    with pytest.raises(ValidationError):
        DeviceUpdate(hostname="not a hostname!")


def test_validation_rejects_uppercase_capability_names() -> None:
    """Capability names must remain lowercase, portable identifiers, not enums."""
    with pytest.raises(ValidationError):
        CapabilityInput(capability="GPIO", version="1.0")


# --- API ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_registers_filters_and_maps_domain_errors(database: Database) -> None:
    """The API uses injected services, pagination, and RFC 7807 errors."""
    app: FastAPI = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
        )
    )
    app.state.container.database.override(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/devices", json=device_payload())
        assert created.status_code == 201
        device_id = created.json()["id"]

        fetched = await client.get(f"/devices/{device_id}")
        assert fetched.status_code == 200
        assert fetched.json()["device_name"] == "garden-node"

        listed = await client.get("/devices", params={"capability": "gpio", "limit": 1})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        duplicate = await client.post("/devices", json=device_payload())
        assert duplicate.status_code == 409
        assert duplicate.headers["content-type"].startswith("application/problem+json")

        invalid = await client.post("/devices", json=device_payload(name="Not Valid"))
        assert invalid.status_code == 422

        updated = await client.put(
            f"/devices/{device_id}", json={"display_name": "Greenhouse node"}
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Greenhouse node"

        good_heartbeat = await client.post(
            f"/devices/{device_id}/heartbeat",
            json={"status": "ONLINE", "agent_version": "1.0", "protocol_version": "1.0"},
        )
        assert good_heartbeat.status_code == 200
        assert good_heartbeat.json()["status"] == "ONLINE"

        capabilities = await client.put(
            f"/devices/{device_id}/capabilities",
            json={"capabilities": [{"capability": "camera", "version": "1.0"}]},
        )
        assert capabilities.status_code == 200
        assert [c["capability"] for c in capabilities.json()["capabilities"]] == ["camera"]

        disabled = await client.post(f"/devices/{device_id}/disable")
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "DISABLED"

        bad_heartbeat = await client.post(
            f"/devices/{device_id}/heartbeat",
            json={"status": "ONLINE", "agent_version": "1", "protocol_version": "1"},
        )
        assert bad_heartbeat.status_code == 422

        enabled = await client.post(f"/devices/{device_id}/enable")
        assert enabled.status_code == 200
        assert enabled.json()["status"] == "UNKNOWN"

        deleted = await client.delete(f"/devices/{device_id}")
        assert deleted.status_code == 204
        missing = await client.get(f"/devices/{device_id}")
        assert missing.status_code == 404

        missing_heartbeat = await client.post(
            f"/devices/{device_id}/heartbeat",
            json={"status": "ONLINE", "agent_version": "1.0", "protocol_version": "1.0"},
        )
        assert missing_heartbeat.status_code == 404


@pytest.mark.asyncio
async def test_api_returns_503_without_configured_database() -> None:
    """The Device Registry endpoints fail safely when no database is configured."""
    app: FastAPI = create_app(Settings(ENVIRONMENT=Environment.TEST))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/devices")
    assert response.status_code == 503


# --- Migration ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_metadata_contains_required_tables(database: Database) -> None:
    """The model metadata used by the migration exposes both registry tables."""
    async with database._engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert {"devices", "device_capabilities"}.issubset(table_names)
