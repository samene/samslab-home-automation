"""Integration: registering a device through the real REST API."""

from __future__ import annotations

from uuid import UUID

from tests.utils.server_harness import ServerHarness


async def test_device_registration_persists_and_is_readable(server: ServerHarness) -> None:
    """A registered device is immediately readable back through REST, enabled by default."""
    device_id = await server.register_device(display_name="Greenhouse Pi")

    device = await server.get_device(device_id)

    assert device["id"] == str(device_id)
    assert device["display_name"] == "Greenhouse Pi"
    assert device["enabled"] is True
    assert device["status"] == "REGISTERING"


async def test_device_registration_persists_capabilities(server: ServerHarness) -> None:
    """Declared capabilities are persisted and readable back."""
    device_id = await server.register_device(
        capabilities=[{"capability": "gpio", "version": "1.0.0", "configuration": {}}]
    )

    device = await server.get_device(device_id)

    assert len(device["capabilities"]) == 1
    assert device["capabilities"][0]["capability"] == "gpio"


async def test_duplicate_device_name_is_rejected(server: ServerHarness) -> None:
    """Registering the same device_name twice is a conflict, not a silent duplicate."""
    await server.register_device(device_name="duplicate-pi")

    response = await server.http.post(
        "/devices",
        json={
            "device_name": "duplicate-pi",
            "hostname": "duplicate-pi.local",
            "display_name": "Duplicate Pi",
        },
    )

    assert response.status_code == 409


async def test_getting_an_unregistered_device_is_not_found(server: ServerHarness) -> None:
    """Fetching a device_id that was never registered returns 404."""
    response = await server.http.get(f"/devices/{UUID(int=0)}")
    assert response.status_code == 404


async def test_registered_device_appears_in_device_list(server: ServerHarness) -> None:
    """A newly registered device shows up in the paginated device list."""
    device_id = await server.register_device()

    response = await server.http.get("/devices")
    response.raise_for_status()
    page = response.json()

    assert any(item["id"] == str(device_id) for item in page["items"])
