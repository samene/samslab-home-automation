# API Design

## Purpose

Set REST API conventions for the web UI and administrative clients.

## Scope

The API manages server-owned resources; agent control is translated to durable commands rather than direct device calls.

## Architecture

Use versioned paths such as `/api/v1`, JSON Pydantic request/response models, OAuth/JWT bearer authentication, and consistent error envelopes containing a stable code, safe message, details where authorized, and request ID. Candidate resources are agents, devices, commands, command status, events, schedules, media metadata, and health/metrics endpoints.

Mutations validate authorization and write an audit record. A command creation response returns `202 Accepted` with its UUID and status URL; terminal results are obtained by polling, UI subscriptions, or a future notification channel. Use cursor pagination, ISO 8601 UTC timestamps, UUIDs, optimistic concurrency where configuration changes can conflict, and idempotency keys for client retries.

### Device Registry (implemented)

`server/app/domains/devices/api.py` implements administrative CRUD over the device inventory only; no authentication, WebSocket, or command dispatch exists yet, so every route below is unauthenticated and hardware-free.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/devices` | List devices; bounded offset/limit pagination (`offset`, `limit` 1-100, default 50) with `status`, `enabled`, `capability`, and `search` (name/display-name substring) filters |
| `GET` | `/devices/{id}` | Fetch one active device |
| `POST` | `/devices` | Register a device and its initial capabilities; `201` |
| `PUT` | `/devices/{id}` | Update `hostname`, `display_name`, `description`, `metadata` only — never status or heartbeat fields |
| `POST` | `/devices/{id}/heartbeat` | Update `status`, `agent_version`, `protocol_version`, `last_seen` only |
| `PUT` | `/devices/{id}/capabilities` | Atomically replace the full capability set |
| `POST` | `/devices/{id}/enable` | Re-enable a device; returns it to `UNKNOWN` pending its next heartbeat |
| `POST` | `/devices/{id}/disable` | Disable a device without deleting it |
| `DELETE` | `/devices/{id}` | Soft-delete (`deleted_at`); `204` |

Request bodies are the domain's own `schemas.py` models (`DeviceCreate`, `DeviceUpdate`, `HeartbeatInput`, `CapabilityReplace`) — reused as-is since they are already framework-independent Pydantic. Responses are the application layer's `DeviceDTO`/`DevicePageDTO` (`app/application/dto/`), never a domain model or SQLAlchemy entity. Errors use RFC 7807 `application/problem+json`, mapped by the single application-wide handler: `DeviceNotFoundError` → `404`, `DeviceAlreadyExistsError`/`DuplicateCapabilityError` → `409`, `InvalidHeartbeatError` → `422`, and request validation failures → `422`.

### Command domain (implemented)

`server/app/domains/commands/api.py` implements command intent management only — it never contacts a device. No WebSocket dispatch, agent transport, or scheduler exists yet; a command created here sits in `PENDING` until a future transport phase calls the service's `mark_dispatched`/`mark_running`/`complete_command`/`fail_command` methods, which are implemented and tested but have no REST route in this phase.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/commands` | Create an immutable command targeting an existing, enabled device; `201` |
| `GET` | `/commands` | List commands; bounded offset/limit pagination (1-100, default 50) with `status`, `device`, `priority`, `command_type`, `created_after`, `created_before` filters and a validated `sort` (`[-]created_at\|scheduled_at\|expires_at\|priority\|status`, default `-created_at`) |
| `GET` | `/commands/{id}` | Fetch one command with its terminal result (if any) and full event trail |
| `POST` | `/commands/{id}/cancel` | Cancel a command that has not yet reached a terminal state; optional `{"reason": "..."}` body recorded on the cancellation event |

`GET /commands` returns the lightweight `CommandDTO` shape (no result/events) for each item; `GET /commands/{id}`, `POST /commands`, and `POST /commands/{id}/cancel` return the richer `CommandDetailDTO`, which nests the single `CommandResultDTO` (or `null`) and the ordered `CommandEventDTO` list — matching the domain's "results and events are stored separately from the payload" persistence philosophy while still composing them for a convenient single-resource read. Both DTOs live in `app/application/dto/`, never the domain's SQLAlchemy models.

Errors use RFC 7807 `application/problem+json`: `CommandNotFoundError`/`DeviceNotFoundError` → `404`, `InvalidCommandStateError`/`DeviceDisabledError` → `409`, and request validation failures (malformed `command_type`, an `expires_at` that leaves no time to run, an out-of-range `max_retries`) → `422`. Confirming the target device exists and is enabled is an application-layer check (`CommandApplicationService`), not the Command domain's — see [Components](COMPONENTS.md).

### Camera (implemented)

`server/app/api/camera.py` implements live camera stream lifecycle entirely through the existing Command domain — there is no Camera domain or persisted model. Unlike every other command-creating route, `POST /camera/start`/`POST /camera/stop` do not return immediately after creating a command: `CameraApplicationService` waits (bounded by `CAMERA_COMMAND_TIMEOUT_SECONDS`, polling every `CAMERA_COMMAND_POLL_INTERVAL_SECONDS`) for the resulting `camera.stream.start`/`camera.stream.stop` command to reach a terminal state before responding, so a `200` response always means the device has actually confirmed the stream started or stopped — never merely that a command was queued. This is a deliberate exception to this document's usual "`202 Accepted` plus a status URL, terminal results obtained by polling" pattern, justified by the frontend need to open the live-stream viewer only once a `playback_url` is actually known to be live.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/camera/start` | Dispatch `camera.stream.start` to the primary device and wait for it to confirm the stream is live |
| `POST` | `/camera/stop` | Dispatch `camera.stream.stop` and wait for it to confirm the stream has stopped |
| `GET` | `/camera/status` | Derive current running/idle state from the most recent completed start/stop commands, with no new command dispatched |

`POST /camera/start` and `GET /camera/status` both return `CameraStatusDTO` (`running`, `stream_name`, `playback_url`, `resolution`, `fps`, `started_at`, `uptime_seconds`, `viewer_count` — the last always `0` today, a documented placeholder). `POST /camera/stop` returns `CameraStopDTO` (`status`, `duration_seconds`, `frames_sent`, `stopped_at`). `playback_url` is always built server-side from `MEDIAMTX_HOST`/`MEDIAMTX_PLAYBACK_PORT`/`CAMERA_STREAM_NAME` configuration — never a URL string reported by the device — so the frontend never hardcodes or otherwise derives a MediaMTX URL itself. Both DTOs live in `app/application/dto/camera_dto.py`.

Errors use RFC 7807 `application/problem+json`: `CameraDeviceNotFoundError` (no device registered to target) → `404`, `CameraCommandFailedError` (the device reported failure)/`CameraCommandTimedOutError` (no result arrived in time) → `409`. See [Camera](../agent/CAMERA.md) for the full command lifecycle and MediaMTX integration, and [Architecture](ARCHITECTURE.md) for why this service opens a fresh session per step rather than one session per request.

### Auth (implemented)

`server/app/domains/auth/api.py` implements authentication only; no route in this phase requires a specific role or permission (see [Security](SECURITY.md) for the full JWT/RBAC design). Every other domain's future protected routes will depend on `CurrentUser`/`CurrentDevice`/`RequireRole`/`RequirePermission` (`app/domains/auth/dependencies.py`), which are already implemented and tested but not yet applied to the Devices or Commands routers in this phase.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/login` | Exchange a username/password for an access/refresh token pair |
| `POST` | `/auth/refresh` | Exchange a valid refresh token for a fresh pair, revoking the one presented |
| `POST` | `/auth/logout` | Revoke a refresh token; idempotent for an unknown or already-revoked token |
| `GET` | `/auth/me` | Return the authenticated user's own profile (requires a user-typed bearer token) |

Login/refresh responses are `TokenPairDTO` (`access_token`, `refresh_token`, `token_type: "bearer"`, `expires_in`); `/auth/me` returns `UserDTO`. A device (agent) never uses these four routes — `issue_device_token`/`rotate_device_secret`/`issue_device_credential` are implemented at the service and application layer (`AuthApplicationService`) for a future transport phase to call, with no REST route yet, matching the same "capability now, route later" pattern used for the Command domain's dispatch methods.

Errors use RFC 7807 `application/problem+json`: `InvalidCredentialsError`/`ExpiredTokenError`/`InvalidTokenError`/`DisabledAccountError`/`DisabledDeviceError` → `401` (with a `WWW-Authenticate: Bearer` header), `PermissionDeniedError`/a failed `RequireRole`/`RequirePermission` check → `403`, `DeviceCredentialNotFoundError` → `404`, `DeviceCredentialAlreadyExistsError` → `409`.

## Design Decisions

REST is a server control-plane API. It never tunnels a browser directly to agent hardware and never exposes credentials for PostgreSQL or internal drivers.

## Future Considerations

OpenAPI publication, scoped API keys, webhooks, and rate plans can be added when external integrations become a product need.

## Open Questions

Which first-release UI actions require synchronous acknowledgement versus asynchronous command tracking?

## References

- [Protocol](PROTOCOL.md)
- [Security](SECURITY.md)
