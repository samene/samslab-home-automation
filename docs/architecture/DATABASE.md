# Database Design

## Purpose

Describe the initial PostgreSQL metadata model without committing to SQL or an ORM.

## Scope

The server database only. Agent offline state belongs in SQLite and is not replicated as a database dependency.

## Architecture

| Table | Purpose | Key relationships / indexes |
| --- | --- | --- |
| `agents` | enrolled agent identity, status, capabilities | unique agent identity; site index |
| `devices` | logical hardware and driver configuration | agent FK; unique agent/device key |
| `commands` | command request and lifecycle | agent/device FK; UUID unique; status/created index |
| `command_attempts` | delivery/execution audit trail | command FK; attempt/time index |
| `events` | deduplicated telemetry and domain events | agent FK; agent sequence unique; time index |
| `media_objects` | object metadata, checksum, retention | device/event FK; object key unique |
| `schedules` | desired recurring command definitions | target agent/device FK; next-run index |
| `users`, `roles`, `sessions` | web identity and authorization audit | unique identity; expiration index |
| `audit_log` | immutable security/administrative events | actor/time index |

Relationships preserve ownership: an agent has devices, commands, events, and schedules; commands have attempts; events may reference media. Store UTC timestamps and immutable UUID identifiers. Use pagination-safe time/ID indexes for high-volume streams.

### Device Registry (implemented)

The `devices` and `device_capabilities` tables are implemented and migrated (`alembic/versions/20260715_0001_create_device_registry.py`), independent of the `agents` FK described above since agent enrollment does not exist yet.

| Table | Columns | Notes |
| --- | --- | --- |
| `devices` | `id` (UUID PK), `device_name` (unique, indexed), `hostname`, `display_name`, `description`, `status`, `last_seen`, `agent_version`, `protocol_version`, `registered_at`, `updated_at`, `enabled`, `deleted_at`, `metadata` (JSONB) | Soft-deleted via `deleted_at`; never hard-deleted so names and history remain auditable |
| `device_capabilities` | `id` (UUID PK), `device_id` (FK, `ON DELETE CASCADE`), `capability`, `version`, `configuration` (JSONB) | Unique on `(device_id, capability)`; `capability` is a free-form string, never an enum, so new hardware types need no server change |

`status` is one of `REGISTERING`, `ONLINE`, `OFFLINE`, `UNHEALTHY`, `DISCONNECTED`, `DISABLED`, `UNKNOWN`. A device starts `REGISTERING` at creation; only a heartbeat (`last_seen`, `status`, `agent_version`, `protocol_version`) or an explicit enable/disable call changes it thereafter. Capability replacement is atomic: existing rows for a device are cleared and flushed before the new set is inserted, so replacements that re-declare an already-present capability name never collide with the outgoing rows on the `(device_id, capability)` constraint.

### Command domain (implemented)

The `commands`, `command_results`, and `command_events` tables are implemented and migrated (`alembic/versions/20260715_0002_create_command_domain.py`), chained after the Device Registry migration since `commands.device_id` is a foreign key to `devices.id`.

| Table | Columns | Notes |
| --- | --- | --- |
| `commands` | `id` (UUID PK), `device_id` (FK → `devices.id`), `command_type`, `status`, `priority`, `payload` (JSONB), `requested_by`, `created_at`, `scheduled_at`, `started_at`, `completed_at`, `expires_at`, `correlation_id`, `trace_id`, `retry_count`, `max_retries` | Immutable once created — `payload` is never rewritten; only `status` and the timestamp columns evolve, only through the state machine |
| `command_results` | `id` (UUID PK), `command_id` (FK, unique, `ON DELETE CASCADE`), `success`, `exit_code`, `result` (JSONB), `error_message`, `duration_ms`, `completed_at` | One row per command, ever — the unique constraint on `command_id` enforces "completed commands cannot restart" at the database level |
| `command_events` | `id` (UUID PK), `command_id` (FK, `ON DELETE CASCADE`), `event_type`, `timestamp`, `details` (JSONB) | Append-only audit trail; one row per state-machine transition, never updated or deleted |

Indexes on `commands` cover `device_id`, `command_type`, `status`, `priority`, `created_at`, `expires_at`, `correlation_id`, plus a composite `(device_id, status, created_at)` index for the dispatch-queue query pattern a future scheduler/transport will use. `status` is one of `PENDING`, `QUEUED`, `DISPATCHED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`, `TIMEOUT`; `priority` is `LOW`, `NORMAL`, `HIGH`, `CRITICAL`, ordered by an explicit rank map rather than string sort. `command_type` is a free-form, dot-namespaced string (e.g. `pump.start`, `camera.capture`) — never an enum — so new command types never require a server change. See [Components](COMPONENTS.md) for the state machine and [API](API.md) for the REST surface.

### Auth (implemented)

The `users`, `roles`, `permissions`, `user_roles`, `device_credentials`, and `refresh_tokens` tables are implemented and migrated (`alembic/versions/20260715_0003_create_auth_domain.py`, chained after the Command domain migration), which also seeds the default role and permission catalog rows on `upgrade()`.

| Table | Columns | Notes |
| --- | --- | --- |
| `users` | `id` (UUID PK), `username` (unique), `email` (unique), `password_hash`, `enabled`, `created_at`, `updated_at`, `last_login` | `password_hash` is Argon2; plaintext is never persisted or logged |
| `roles` | `id` (UUID PK), `name` (unique), `description` | Seeded with `Admin`, `Viewer`, `Agent` — see [Security](SECURITY.md) |
| `permissions` | `id` (UUID PK), `name` (unique), `description` | A reference catalog only (`devices.read`, `devices.write`, `commands.read`, `commands.execute`, `files.read`, `files.upload`, `system.admin`); a role's actual permission set is resolved from `app/domains/auth/permissions.py`'s `ROLE_PERMISSIONS` map, not by joining this table at request time |
| `user_roles` | `user_id` (FK, `ON DELETE CASCADE`), `role_id` (FK, `ON DELETE CASCADE`) | Composite PK; a plain association table (no ORM entity of its own), many-to-many |
| `device_credentials` | `id` (UUID PK), `device_id` (FK → `devices.id`, unique), `client_id` (unique), `client_secret_hash`, `enabled`, `created_at`, `last_rotated` | One credential per device; `client_secret_hash` is Argon2, never plaintext |
| `refresh_tokens` | `id` (UUID PK), `user_id` (FK, `ON DELETE CASCADE`), `token_hash` (unique), `expires_at`, `revoked_at`, `created_at` | Users only — devices re-authenticate with `client_id`/`client_secret` instead of holding a refresh token; `token_hash` is a SHA-256 digest of an opaque random value, never the token itself |

See [Security](SECURITY.md) for the full JWT/RBAC/token-lifecycle design this schema supports.

### Snapshots (implemented)

The `snapshots` table is implemented and migrated (`alembic/versions/20260718_0004_create_snapshots_table.py`, chained after the Auth domain migration), since `snapshots.device_id`/`snapshots.command_id` are foreign keys to `devices.id`/`commands.id`.

| Table | Columns | Notes |
| --- | --- | --- |
| `snapshots` | `id` (UUID PK), `device_id` (FK → `devices.id`), `command_id` (FK → `commands.id`, unique), `filename`, `bucket`, `original_object_key`, `thumbnail_object_key`, `etag`, `sha256`, `width`, `height`, `size`, `captured_at`, `created_at`, `metadata` (JSONB) | **Hard-deleted**, unlike every other table above — a snapshot's whole point is a real S3 object, so `DELETE /snapshots/{id}` removes the row itself (`session.delete`) rather than setting a `deleted_at` timestamp; the unique constraint on `command_id` enforces "one snapshot per `camera.snapshot` command," mirroring `command_results`' unique `command_id` |

Only object keys are stored — `bucket`/`original_object_key`/`thumbnail_object_key` — never a URL. `GET /snapshots`/`GET /snapshots/{id}` mint a fresh, short-lived presigned S3 URL on every response (`AWS_PRESIGNED_URL_TTL_SECONDS`); nothing about a snapshot's *readable* location is ever persisted, so a bucket/CDN migration never requires a data migration, only a settings change. Indexes cover `device_id`, `command_id`, and `captured_at` (the Gallery's newest-first sort key). See [Camera](../agent/CAMERA.md) for the full capture → upload → persist → presigned-read flow.

## Design Decisions

PostgreSQL is authoritative for server metadata and lifecycle state. Migrations are ordered, reviewed, reversible where feasible, and run once by controlled deployment. Retention is policy-driven: operational command/audit history is retained longer than raw telemetry; object lifecycle policies delete or archive binary media independently.

## Future Considerations

Partition high-volume events by time; add rollups, read replicas, per-site boundaries, and archival exports when supported by observed load.

## Open Questions

- Required retention periods by data classification?
- Will a future identity provider (delegated auth/SSO) replace or supplement the current local `users` table?

## References

- [Architecture](ARCHITECTURE.md)
- [Storage](../agent/STORAGE.md)
