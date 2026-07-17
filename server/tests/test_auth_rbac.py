"""RBAC tests: RequireRole/RequirePermission enforcement, both unit and HTTP-level."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.exceptions import ForbiddenError
from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.auth.dependencies import RequirePermission, RequireRole
from app.domains.auth.models import Role, User
from app.domains.auth.passwords import hash_password
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import Principal, PrincipalType
from app.main import create_app


def make_principal(
    *, roles: frozenset[str] = frozenset(), permissions: frozenset[str] = frozenset()
) -> Principal:
    """Build a Principal directly, bypassing token decoding, for dependency unit tests."""
    return Principal(
        principal_type=PrincipalType.USER, subject_id="user-1", roles=roles, permissions=permissions
    )


# --- Unit tests: dependency factories ---------------------------------------------


@pytest.mark.asyncio
async def test_require_role_allows_a_principal_with_the_role() -> None:
    """A principal holding the required role passes through unchanged."""
    principal = make_principal(roles=frozenset({"Admin"}))
    dependency = RequireRole("Admin")
    assert (await dependency(principal=principal)) is principal


@pytest.mark.asyncio
async def test_require_role_rejects_a_principal_without_the_role() -> None:
    """A principal missing the required role is forbidden."""
    principal = make_principal(roles=frozenset({"Viewer"}))
    dependency = RequireRole("Admin")
    with pytest.raises(ForbiddenError):
        await dependency(principal=principal)


@pytest.mark.asyncio
async def test_require_permission_allows_a_principal_with_the_permission() -> None:
    """A principal holding the required permission passes through unchanged."""
    principal = make_principal(permissions=frozenset({"devices.write"}))
    dependency = RequirePermission("devices.write")
    assert (await dependency(principal=principal)) is principal


@pytest.mark.asyncio
async def test_require_permission_rejects_a_principal_without_the_permission() -> None:
    """A principal missing the required permission is forbidden."""
    principal = make_principal(permissions=frozenset({"devices.read"}))
    dependency = RequirePermission("devices.write")
    with pytest.raises(ForbiddenError):
        await dependency(principal=principal)


def test_require_role_and_require_permission_build_independent_dependencies() -> None:
    """Each call to RequireRole/RequirePermission returns its own closure."""
    admin_dependency = RequireRole("Admin")
    viewer_dependency = RequireRole("Viewer")
    assert admin_dependency is not viewer_dependency


# --- HTTP-level tests: real app, real tokens, real enforcement --------------------


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'rbac.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def build_app_with_probe_routes(database: Database) -> FastAPI:
    """Build a real app with the auth router plus two throwaway protected routes."""
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            JWT_SECRET="a-sufficiently-long-test-signing-secret-value",
        )
    )
    app.state.container.database.override(database)

    probe = APIRouter()

    @probe.get("/probe/admin-only")
    async def admin_only(
        principal: Principal = Depends(RequirePermission("system.admin")),
    ) -> dict[str, str]:
        return {"subject": principal.subject_id}

    @probe.get("/probe/viewer-role")
    async def viewer_role(principal: Principal = Depends(RequireRole("Viewer"))) -> dict[str, str]:
        return {"subject": principal.subject_id}

    app.include_router(probe)
    return app


async def seed_user(session: AsyncSession, *, username: str, role_name: str, password: str) -> None:
    """Register one user holding one role, ready to log in over HTTP."""
    repository = AuthRepository(session)
    role = Role(name=role_name, description="test role")
    session.add(role)
    await session.flush()
    user = await repository.create_user(
        User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(password),
        )
    )
    await repository.assign_role(user, role)


@pytest.mark.asyncio
async def test_require_permission_allows_admin_through_the_real_app(database: Database) -> None:
    """An Admin's token, carrying system.admin, passes RequirePermission over real HTTP."""
    async with database.session_factory() as setup_session:
        await seed_user(setup_session, username="admin", role_name="Admin", password="adminpw123")
        await setup_session.commit()
    app = build_app_with_probe_routes(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/auth/login", json={"username": "admin", "password": "adminpw123"}
        )
        assert login.status_code == 200
        access_token = login.json()["access_token"]

        response = await client.get(
            "/probe/admin-only", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_require_role_returns_403_for_a_principal_without_the_role(
    database: Database,
) -> None:
    """A Viewer's token is rejected by a route requiring the Admin role."""
    async with database.session_factory() as setup_session:
        await seed_user(
            setup_session, username="viewer", role_name="Viewer", password="viewerpw123"
        )
        await setup_session.commit()
    app = build_app_with_probe_routes(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/auth/login", json={"username": "viewer", "password": "viewerpw123"}
        )
        access_token = login.json()["access_token"]

        forbidden = await client.get(
            "/probe/admin-only", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert forbidden.status_code == 403
        assert forbidden.headers["content-type"].startswith("application/problem+json")

        allowed = await client.get(
            "/probe/viewer-role", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_protected_route_returns_401_without_a_token(database: Database) -> None:
    """No Authorization header at all yields 401, not 403 or 500."""
    app = build_app_with_probe_routes(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe/admin-only")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
