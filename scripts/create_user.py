#!/usr/bin/env python3.13
"""Create (or update) a human user who can log in through ``POST /auth/login``.

Nothing in the running application currently creates the first user account —
there is no registration endpoint by design (user provisioning is an
administrative action, not self-service) — so this script exists to make the
Auth domain's already-implemented login flow actually usable in a fresh
development database. It also seeds the ``roles`` table from
``app.domains.auth.permissions.DEFAULT_ROLES`` if empty, since nothing else
does that outside of tests either.

Usage (run from the repo root, with the server's virtualenv active):

    python scripts/create_user.py --username admin --email admin@example.com \\
        --password 'change-me' --role Admin

Requires ``DATABASE_URL`` to point at an already-migrated database
(``alembic upgrade head``) — this script never creates schema.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parent.parent / "server"
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.config.settings import Settings  # noqa: E402
from app.core.database import Database  # noqa: E402
from app.domains.auth.models import Role, User  # noqa: E402
from app.domains.auth.passwords import hash_password  # noqa: E402
from app.domains.auth.permissions import DEFAULT_ROLES  # noqa: E402
from app.domains.auth.repository import AuthRepository  # noqa: E402


async def _ensure_role(repository: AuthRepository, name: str) -> Role:
    role = await repository.find_role_by_name(name)
    if role is not None:
        return role
    description = next((desc for role_name, desc in DEFAULT_ROLES if role_name == name), None)
    if description is None:
        raise SystemExit(f"Unknown role {name!r}; expected one of {[n for n, _ in DEFAULT_ROLES]}")
    return await repository.create_role(Role(name=name, description=description))


async def create_user(
    *, username: str, email: str, password: str, role: str, database_url: str
) -> None:
    database = Database(database_url)
    try:
        async with database.session_factory() as session:
            repository = AuthRepository(session)
            existing = await repository.find_user_by_username(username)
            if existing is not None:
                print(f"User {username!r} already exists (id={existing.id}); no changes made.")
                return

            role_row = await _ensure_role(repository, role)
            user = await repository.create_user(
                User(username=username, email=email, password_hash=hash_password(password))
            )
            await repository.assign_role(user, role_row)
            await session.commit()
            print(f"Created user {username!r} (id={user.id}) with role {role!r}.")
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="Admin", choices=[name for name, _ in DEFAULT_ROLES])
    args = parser.parse_args()

    settings = Settings()
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL must be set (see .env / server/app/config/settings.py)")

    asyncio.run(
        create_user(
            username=args.username,
            email=args.email,
            password=args.password,
            role=args.role,
            database_url=settings.database_url.get_secret_value(),
        )
    )


if __name__ == "__main__":
    main()
