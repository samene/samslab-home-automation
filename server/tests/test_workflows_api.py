"""REST API tests for Workflows, mirroring test_snapshots_api.py's structure.

Every test here uses a plain ``httpx.AsyncClient`` over ``ASGITransport`` —
which never runs the ASGI lifespan — for the CRUD/run-trigger routes, since
those need no dispatcher/reconciliation machinery running. The one exception,
``test_lifespan_reconciles_an_interrupted_run_on_startup``, needs the real
``create_app`` lifespan to fire; it drives ``app.main.lifespan`` directly on
the single event loop pytest-asyncio already manages rather than going through
``TestClient`` (which would run the app on a *separate portal thread with its
own event loop* — the same aiosqlite/cross-thread hazard documented in
``test_dispatcher_integration.py``'s module docstring and CLAUDE.md's
WebSocket-Gateway-testing section, here for a plain lifespan instead of a
websocket).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.workflows.models import Workflow, WorkflowRunStatus
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowStepCreate
from app.main import create_app, lifespan


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'workflows_api.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def _app_for(database: Database) -> FastAPI:
    app = create_app(
        Settings(ENVIRONMENT=Environment.TEST, DATABASE_URL="sqlite+aiosqlite:///:memory:")
    )
    app.state.container.database.override(database)
    return app


def _create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Evening Watering",
        "description": "Snapshot then wait",
        "enabled": True,
        "steps": [
            {"step_type": "COMMAND", "command_type": "camera.snapshot"},
            {"step_type": "SLEEP", "sleep_seconds": 5},
        ],
    }
    payload.update(overrides)
    return payload


# --- G. CRUD + run-trigger routes -------------------------------------------


async def test_api_creates_a_workflow_and_returns_full_detail(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/workflows", json=_create_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Evening Watering"
    assert body["enabled"] is True
    assert body["run_count"] == 0
    assert body["last_run_status"] is None
    assert len(body["steps"]) == 2
    assert body["steps"][0]["step_type"] == "COMMAND"
    assert body["latest_run"] is None


async def test_api_lists_workflows_with_pagination(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for index in range(3):
            created = await client.post("/workflows", json=_create_payload(name=f"Workflow {index}"))
            assert created.status_code == 201

        response = await client.get("/workflows", params={"offset": 0, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["offset"] == 0
    assert body["limit"] == 2


async def test_api_gets_one_workflow_by_id(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/workflows", json=_create_payload())
        workflow_id = created.json()["id"]

        response = await client.get(f"/workflows/{workflow_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == workflow_id
    assert len(body["steps"]) == 2
    assert body["latest_run"] is None


async def test_api_get_missing_workflow_returns_404_problem_json(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/workflows/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "WorkflowNotFoundError" in response.json()["type"]


async def test_api_updates_a_workflow_replacing_its_steps(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/workflows", json=_create_payload())
        workflow_id = created.json()["id"]

        response = await client.put(
            f"/workflows/{workflow_id}",
            json={
                "name": "Evening Watering (v2)",
                "enabled": True,
                "steps": [{"step_type": "SLEEP", "sleep_seconds": 42}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Evening Watering (v2)"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["step_type"] == "SLEEP"
    assert body["steps"][0]["sleep_seconds"] == 42


async def test_api_deletes_a_workflow_then_get_returns_404(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/workflows", json=_create_payload())
        workflow_id = created.json()["id"]

        deleted = await client.delete(f"/workflows/{workflow_id}")
        assert deleted.status_code == 204

        missing = await client.get(f"/workflows/{workflow_id}")
        assert missing.status_code == 404


async def test_api_run_workflow_returns_promptly_with_the_run_marked_running(
    database: Database,
) -> None:
    """No device is registered here on purpose: the background task fails almost

    instantly (a single failed device lookup, no polling loop). This test
    still doesn't wait on it the way test_workflow_service.py's tests do
    (that's not what's under test here) — but it does give the detached task
    a brief moment to settle before returning, purely so a dangling
    ``asyncio.create_task`` doesn't outlive this test's own event loop, which
    a bare-``ASGITransport`` request has no other way to observe finishing.
    """
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/workflows", json=_create_payload())
        workflow_id = created.json()["id"]

        response = await client.post(f"/workflows/{workflow_id}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["latest_run"] is not None
    assert body["latest_run"]["status"] == "RUNNING"
    await asyncio.sleep(0.2)


async def test_api_run_workflow_on_a_disabled_workflow_returns_409(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/workflows", json=_create_payload(enabled=False))
        workflow_id = created.json()["id"]

        response = await client.post(f"/workflows/{workflow_id}/run")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "WorkflowDisabledError" in response.json()["type"]


async def test_api_run_workflow_on_a_missing_id_returns_404(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/workflows/{uuid4()}/run")

    assert response.status_code == 404


async def test_api_create_workflow_with_malformed_step_tree_returns_422(database: Database) -> None:
    """A PARALLEL group with only one child fails WorkflowStepCreate's own validation."""
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/workflows",
            json=_create_payload(
                steps=[
                    {
                        "step_type": "GROUP",
                        "group_mode": "PARALLEL",
                        "children": [{"step_type": "SLEEP", "sleep_seconds": 1}],
                    }
                ]
            ),
        )

    assert response.status_code == 422


# --- F. Startup reconciliation wired through app/main.py's lifespan --------


async def test_lifespan_reconciles_an_interrupted_run_on_startup(database: Database) -> None:
    """A workflow_runs row left RUNNING by a prior process is failed at startup.

    Seeds the row directly through WorkflowRepository (committed in its own
    session), then drives ``app.main.lifespan`` directly — the same context
    manager ``create_app``'s ``FastAPI(lifespan=...)`` uses — on this test's
    own event loop, so ``WorkflowService.reconcile_interrupted_runs`` (called
    before the dispatcher starts) actually runs against the real fixture
    database without a second thread/event loop ever touching it.
    """
    async with database.session_factory() as session:
        repository = WorkflowRepository(session)
        workflow = Workflow(name="Orphaned", description=None, enabled=True)
        await repository.create(workflow, [WorkflowStepCreate(step_type="SLEEP", sleep_seconds=1)])
        run = await repository.create_run(workflow.id)
        await session.commit()
        workflow_id = workflow.id
        run_id = run.id

    app = _app_for(database)
    async with lifespan(app):
        pass

    async with database.session_factory() as session:
        repository = WorkflowRepository(session)
        refreshed_run = await repository.find_run(run_id)
        assert refreshed_run is not None
        assert refreshed_run.status == WorkflowRunStatus.FAILED
        assert refreshed_run.error_message == "interrupted by server restart"

        refreshed_workflow = await repository.find_by_id(workflow_id)
        assert refreshed_workflow is not None
        assert refreshed_workflow.run_count == 1
        assert refreshed_workflow.last_run_status == WorkflowRunStatus.FAILED
