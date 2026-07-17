# Security

## Purpose

Define baseline security controls for a remotely operated home platform.

## Scope

Covers identity, transport, secrets, authorization, data handling, and operations.

## Architecture

All external transport uses modern TLS. The Pi initiates outbound connections only; firewall rules deny unsolicited ingress. Human users authenticate with short-lived JWT access tokens and renewable sessions; agents authenticate with individually revocable credentials bound to agent identity and protocol policy. Authorization is enforced server-side per actor, site, agent, device, and command.

Secrets are supplied through validated environment configuration or a deployment secret manager, never committed or emitted in logs. Use separate least-privilege credentials for database migrations, server runtime, object storage, metrics, and each agent. Support staged key/token rotation, revocation, credential expiry, and audit trails.

### Auth subsystem (implemented)

`server/app/domains/auth/` implements JWT authentication and RBAC authorization for both principal types described above. It is deliberately transport-independent: nothing in `jwt.py`, `passwords.py`, `tokens.py`, `permissions.py`, or `service.py` imports FastAPI, so the same `AuthService` (and the pure `decode_principal` function backing token validation) is what a future WebSocket handshake, gRPC interceptor, or MQTT connector would call too — only `dependencies.py` and `api.py` are FastAPI-specific.

**JWT flow.** Every token is a signed JWT (HS256 by default; algorithm/issuer/audience/expirations/clock skew are all `Settings` fields — `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_ACCESS_TOKEN_TTL_SECONDS`, `JWT_REFRESH_TOKEN_TTL_SECONDS`, `JWT_CLOCK_SKEW_SECONDS`) carrying the standard `sub`/`exp`/`iat`/`iss`/`aud`/`jti` claims plus `role` (the principal's role names), `permissions` (already resolved and flattened at issuance — see RBAC below), `principal_type` (`USER` or `DEVICE`), and `device_id` for a device token. Resolving a bearer token to a `Principal` (`CurrentPrincipal` in `dependencies.py`) is therefore a pure JWT decode with no database access — authorizing a request never costs a query.

**RBAC.** Permissions are plain strings (`devices.read`, `devices.write`, `commands.read`, `commands.execute`, `files.read`, `files.upload`, `system.admin`), never an enum, and no code anywhere hardcodes a permission check against a specific role name. `permissions.py`'s `ROLE_PERMISSIONS` map is the single source of truth for what each of the three default roles (`Admin`, `Viewer`, `Agent`) grants; `permissions_for_roles()` unions the permissions of however many roles a user holds. `CurrentUser`/`CurrentDevice` narrow a resolved principal to one type; `RequireRole(name)`/`RequirePermission(name)` build a reusable FastAPI dependency checking the already-resolved token claims — no route in this phase uses them yet, but every future protected endpoint (on any domain) is expected to depend on one of these four rather than reimplementing a check.

**Device authentication.** A device (agent) never uses `/auth/login`; it proves possession of an RSA private key it holds permanently, never a shared secret. `AuthService.issue_device_credential()` (called via `scripts/create_device.py`, since there's no self-service device registration) generates an RSA keypair, persists only the *public* key (`device_credentials.public_key_pem`), and returns the private key exactly once — the operator pastes it into the agent's `.env` as `DEVICE_PRIVATE_KEY` (base64-encoded PKCS8 PEM, to survive a bash-sourced `.env` unscathed) and never again. To authenticate, the agent signs a short-lived (60s), single-use JWT assertion (`sub: client_id`, `RS256`) with that key and calls `POST /auth/device/token`; `issue_device_token()` looks up the credential by `client_id`, verifies the assertion's signature against the *stored public key* (with the algorithm pinned to RS256 server-side — never read from the assertion's own header, closing off the classic "algorithm confusion" attack), checks `sub == client_id`, and if valid mints a normal short-lived access token with `principal_type: DEVICE` — a device has no refresh token, since it can always sign a fresh assertion instead. `rotate_device_key()` replaces a credential's public key (recording `last_rotated`); the previous private key stops working immediately, since the server no longer holds a matching public key for it. Confirming the target device exists (and, for issuance, doesn't already have a credential) is enforced by `AuthApplicationService`, not the Auth domain itself — the same cross-domain-check-belongs-in-the-application-layer rule the Command domain follows for its own device checks.

This design replaced an earlier one where the agent held a static, pre-issued access token directly (`DEVICE_TOKEN`, 15-minute default TTL) rather than a key it could use to mint fresh ones — once that token expired while the agent was disconnected (a lost WiFi connection, a server restart, or a `RECONNECT_INTERVAL`-driven retry loop spanning longer than the TTL), the agent had no way to obtain a new one short of an operator manually re-running the provisioning script and redeploying `.env`. `ConnectionManager.authenticate()` now calls `fetch_device_token()` (`agent/app/connection/token_provider.py`) fresh on *every* connection attempt rather than reading a cached value, since a private key never expires — so a reconnect always succeeds no matter how long the disconnection lasted, with zero operator intervention.

**Token lifecycle and refresh tokens.** Access tokens are short-lived (15 minutes by default) and stateless/unrevocable before expiry — that's the tradeoff for not costing a database query per request. Refresh tokens are the opposite: long-lived (14 days by default), opaque random strings (never a JWT), stored only as a SHA-256 hash (`refresh_tokens.token_hash`) so a database compromise doesn't yield directly reusable tokens. Every `POST /auth/refresh` call **rotates**: the presented refresh token is revoked (`revoked_at` stamped) in the same transaction that issues the new pair, so a stolen-and-replayed refresh token is detected the next time its legitimate owner refreshes (both ends now hold an invalidated token). `POST /auth/logout` revokes a refresh token directly. Disabling a user account or a device credential takes effect immediately on the next login/refresh/token-issuance attempt, independent of any outstanding access token's remaining lifetime.

## Design Decisions

- PostgreSQL is private to the server network; the agent has no database credential or route.
- Object uploads use narrowly scoped, time-limited authorization rather than broad storage credentials on the Pi.
- Validate every protocol/API boundary; minimize media and location metadata exposure.
- Passwords are Argon2-hashed; refresh tokens are opaque random values, SHA-256-hashed at rest — neither is ever stored or logged in plaintext. Device credentials are asymmetric keypairs instead of a shared secret: only the *public* key is ever persisted server-side, and the matching private key is shown to the operator exactly once, at issuance/rotation.
- A login failure never distinguishes "unknown username" from "wrong password" (both raise the same `InvalidCredentialsError`), to avoid username enumeration.

## Future Considerations

Hardware-backed keys, mTLS, secret-manager integration, dependency scanning, threat modeling, and incident runbooks should be introduced before broader deployment. For the Auth subsystem specifically: a per-principal-type (user vs. device) signing key, automated/scheduled device key rotation (today `rotate_device_key()` exists but nothing calls it on a cadence), MFA for human users, replay protection for device assertions (today bounded only by a 60-second `exp`, not a tracked `jti`), and a `jti`-based access-token revocation list for compromise response before natural expiry.

## Open Questions

What identity provider, MFA requirement, and recovery process are suitable for the owner?

## References

- [Architecture](ARCHITECTURE.md)
- [Deployment](DEPLOYMENT.md)
