"""REST API tests for Schedules, mirroring test_workflows_api.py's structure.

Every test uses a plain ``httpx.AsyncClient`` over ``ASGITransport`` (no real
lifespan, so the live scheduler never actually starts) except
``test_lifespan_reloads_enabled_schedules_on_startup``, which drives
``app.main.lifespan`` directly on this test's own event loop — the same
reasoning ``test_workflows_api.py``'s own lifespan test documents (avoiding
``TestClient``'s separate-portal-thread aiosqlite hazard).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.main import create_app, lifespan


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'schedules_api.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def _app_for(database: Database) -> FastAPI:
    app = create_app(
        Settings(ENVIRONMENT=Environment.TEST, DATABASE_URL="sqlite+aiosqlite:///:memory:")
    )
    app.state.container.database.override(database)
    return app


def _workflow_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Nightly patrol",
        "steps": [{"step_type": "SLEEP", "sleep_seconds": 1}],
    }
    payload.update(overrides)
    return payload


async def _create_workflow(client: httpx.AsyncClient, **overrides: object) -> str:
    response = await client.post("/workflows", json=_workflow_payload(**overrides))
    assert response.status_code == 201
    workflow_id: str = response.json()["id"]
    return workflow_id


def _schedule_payload(workflow_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "workflow_id": workflow_id,
        "name": "Every five minutes",
        "description": "Runs often",
        "enabled": True,
        "schedule_type": "CRON",
        "cron_expression": "*/5 * * * *",
        "timezone": "UTC",
    }
    payload.update(overrides)
    return payload


async def test_api_creates_a_schedule_and_returns_its_full_definition(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        response = await client.post("/schedules", json=_schedule_payload(workflow_id))

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Every five minutes"
    assert body["workflow_id"] == workflow_id
    assert body["workflow_name"] == "Nightly patrol"
    assert body["schedule_type"] == "CRON"
    assert body["run_count"] == 0
    assert body["last_status"] is None


async def test_api_rejects_an_invalid_cron_expression(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        response = await client.post(
            "/schedules", json=_schedule_payload(workflow_id, cron_expression="not a cron")
        )

    assert response.status_code == 422


async def test_api_rejects_a_schedule_for_a_missing_workflow(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/schedules", json=_schedule_payload(str(uuid4())))

    assert response.status_code == 404


async def test_api_gets_and_lists_schedules(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        created = await client.post("/schedules", json=_schedule_payload(workflow_id))
        schedule_id = created.json()["id"]

        get_response = await client.get(f"/schedules/{schedule_id}")
        list_response = await client.get("/schedules")

    assert get_response.status_code == 200
    assert get_response.json()["id"] == schedule_id
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == schedule_id


async def test_api_get_schedule_returns_404_for_a_missing_id(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/schedules/{uuid4()}")

    assert response.status_code == 404


async def test_api_updates_a_schedule(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        created = await client.post("/schedules", json=_schedule_payload(workflow_id))
        schedule_id = created.json()["id"]

        response = await client.put(
            f"/schedules/{schedule_id}",
            json=_schedule_payload(workflow_id, name="Renamed", cron_expression="0 0 * * *"),
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["cron_expression"] == "0 0 * * *"


async def test_api_enable_and_disable_a_schedule(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        created = await client.post("/schedules", json=_schedule_payload(workflow_id))
        schedule_id = created.json()["id"]

        disabled = await client.post(f"/schedules/{schedule_id}/disable")
        enabled = await client.post(f"/schedules/{schedule_id}/enable")

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True


async def test_api_run_now_triggers_the_workflow(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        created = await client.post("/schedules", json=_schedule_payload(workflow_id))
        schedule_id = created.json()["id"]

        response = await client.post(f"/schedules/{schedule_id}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == workflow_id
    assert body["latest_run"] is not None
    assert body["latest_run"]["status"] == "RUNNING"


async def test_api_deletes_a_schedule(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        created = await client.post("/schedules", json=_schedule_payload(workflow_id))
        schedule_id = created.json()["id"]

        delete_response = await client.delete(f"/schedules/{schedule_id}")
        get_response = await client.get(f"/schedules/{schedule_id}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


async def test_api_lists_schedule_executions(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        await client.post("/schedules", json=_schedule_payload(workflow_id))

        response = await client.get("/schedules/executions")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_lifespan_reloads_enabled_schedules_on_startup(database: Database) -> None:
    """A schedule already enabled in the database gets registered live at startup.

    Seeds the workflow/schedule rows directly through a plain REST call
    against a lifespan-less app instance first (identical to how
    ``test_workflows_api.py``'s own reconciliation test seeds via the
    repository), then drives ``app.main.lifespan`` directly on this test's
    own event loop and confirms the live scheduler picked it up — this *is*
    "Reload all enabled schedules automatically" at the REST/lifespan level.
    """
    seed_app = _app_for(database)
    transport = httpx.ASGITransport(app=seed_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        workflow_id = await _create_workflow(client)
        created = await client.post("/schedules", json=_schedule_payload(workflow_id))
        schedule_id = created.json()["id"]

    app = _app_for(database)
    async with lifespan(app):
        scheduler = app.state.container.scheduler()
        assert scheduler.is_running is True
        assert scheduler.next_run_time(schedule_id) is not None
