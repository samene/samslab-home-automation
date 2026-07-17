#!/usr/bin/env python3.13
"""Register a device (if needed) and issue it a keypair-based credential.

There is no REST route for device *registration* yet — per
``docs/architecture/ARCHITECTURE.md``, device provisioning is an
administrative action, not self-service — so this script exists to make the
Auth domain's already-implemented flow usable today, the same way
``create_user.py`` does for human accounts.

Usage (run from the repo root, with the server's virtualenv active):

    python scripts/create_device.py --device-name backyard-pi \\
        --hostname backyard-pi.local --display-name "Backyard Pi"

Prints a client_id and DEVICE_PRIVATE_KEY (shown once — only the matching
public key is stored server-side, and it cannot be recovered from the
database afterward). Paste both, plus AUTH_TOKEN_URL, into the agent's
``.env``.

Unlike the old client_secret design, this credential never expires and
needs no periodic rotation to keep the agent connected: the agent signs a
fresh, short-lived JWT assertion with DEVICE_PRIVATE_KEY on every connection
attempt and exchanges it for a fresh access token via
``POST /auth/device/token`` — see ``app/domains/auth/service.py``'s
``issue_device_token`` and ``docs/architecture/SECURITY.md``. Use --rotate
only if the private key itself may have been compromised.

Requires ``DATABASE_URL`` to point at an already-migrated database
(``alembic upgrade head``) — this script never creates schema.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parent.parent / "server"
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

import jwt as pyjwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from app.config.settings import Settings  # noqa: E402
from app.core.database import Database  # noqa: E402
from app.domains.auth.jwt import JWTCodec  # noqa: E402
from app.domains.auth.repository import AuthRepository  # noqa: E402
from app.domains.auth.service import AuthService, IssuedDeviceCredential  # noqa: E402
from app.domains.devices.exceptions import DeviceAlreadyExists  # noqa: E402
from app.domains.devices.repository import DeviceRepository  # noqa: E402
from app.domains.devices.schemas import DeviceCreate  # noqa: E402
from app.domains.devices.service import DeviceService  # noqa: E402


def _build_self_test_assertion(issued: IssuedDeviceCredential) -> str:
    """Sign a short-lived assertion with the just-issued private key.

    Mirrors exactly what the agent does on every connection attempt (see
    ``agent/app/connection/token_provider.py``) — proving the round trip
    works before the operator ever touches the agent's own ``.env``.
    """
    private_key = serialization.load_pem_private_key(
        base64.b64decode(issued.private_key_b64), password=None
    )
    now = int(time.time())
    return pyjwt.encode(
        {"sub": issued.client_id, "iat": now, "exp": now + 60, "jti": str(uuid.uuid4())},
        private_key,
        algorithm="RS256",
    )


async def create_device(
    *,
    device_name: str,
    hostname: str,
    display_name: str,
    description: str | None,
    rotate: bool,
    settings: Settings,
) -> None:
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL must be set (see .env / server/app/config/settings.py)")
    if settings.jwt_secret is None:
        raise SystemExit("JWT_SECRET must be set (see .env / server/app/config/settings.py)")

    database = Database(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            devices = DeviceService(DeviceRepository(session))
            auth_repository = AuthRepository(session)
            jwt_codec = JWTCodec(
                secret=settings.jwt_secret.get_secret_value(),
                algorithm=settings.jwt_algorithm,
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                clock_skew_seconds=settings.jwt_clock_skew_seconds,
            )
            auth = AuthService(
                auth_repository,
                jwt_codec,
                access_token_ttl=timedelta(seconds=settings.jwt_access_token_ttl_seconds),
                refresh_token_ttl=timedelta(seconds=settings.jwt_refresh_token_ttl_seconds),
            )

            try:
                registered = await devices.register_device(
                    DeviceCreate.model_validate(
                        {
                            "device_name": device_name,
                            "hostname": hostname,
                            "display_name": display_name,
                            "description": description,
                        }
                    )
                )
                print(f"Registered device {device_name!r} (id={registered.id}).")
                device = registered
            except DeviceAlreadyExists:
                existing = await DeviceRepository(session).find_by_name(device_name)
                assert existing is not None
                print(f"Device {device_name!r} already exists (id={existing.id}).")
                device = existing

            existing_credential = await auth_repository.find_device_credential_by_device_id(
                device.id
            )
            if existing_credential is not None and not rotate:
                await session.commit()
                print(
                    f"A credential already exists for this device (client_id="
                    f"{existing_credential.client_id!r}). Its private key can't be retrieved "
                    f"again (only its public key is stored) — re-run with --rotate to replace "
                    f"it and issue a fresh one."
                )
                return

            if existing_credential is not None:
                issued = await auth.rotate_device_key(device.id)
                print(f"Rotated credential for client_id={issued.client_id!r}.")
            else:
                issued = await auth.issue_device_credential(device.id)
                print(f"Issued new credential: client_id={issued.client_id!r}.")

            assertion = _build_self_test_assertion(issued)
            await auth.issue_device_token(client_id=issued.client_id, assertion=assertion)
            await session.commit()

            print()
            print(f"DEVICE_CLIENT_ID={issued.client_id}")
            print(f"DEVICE_PRIVATE_KEY={issued.private_key_b64}")
            print()
            print(
                "Paste both lines above into the agent's .env, along with AUTH_TOKEN_URL "
                "pointing at this server's POST /auth/device/token (e.g. "
                "https://<server>/api/auth/device/token in the hybrid deployment, or "
                "http://localhost:8000/auth/device/token talking to the backend directly)."
            )
            print(
                "Self-test passed: a freshly signed assertion was successfully exchanged for "
                "an access token, confirming the stored public key matches this private key."
            )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device-name", required=True, help="Lowercase, hyphenated, e.g. backyard-pi"
    )
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--description", default=None)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Replace an existing credential (invalidates the old private key) with a fresh one",
    )
    args = parser.parse_args()

    asyncio.run(
        create_device(
            device_name=args.device_name,
            hostname=args.hostname,
            display_name=args.display_name,
            description=args.description,
            rotate=args.rotate,
            settings=Settings(),
        )
    )


if __name__ == "__main__":
    main()
