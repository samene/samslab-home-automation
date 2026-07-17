# Cloud Server Foundation

## Architecture

The server is a FastAPI delivery foundation assembled by `app.main:create_app`. It owns a per-application dependency-injector container and exposes unauthenticated system endpoints plus the Auth, Device Registry, and Command domains. Configuration is validated at the boundary, structured logging and request context are established at lifespan startup, and middleware produces request/correlation IDs plus timing and exception logs.

The Device Registry (`app/domains/devices/`) manages the logical device/capability inventory over REST with PostgreSQL-backed persistence. The Command domain (`app/domains/commands/`) is the central business domain: every action a device performs is an immutable command with an explicit lifecycle state machine, a separately stored terminal result, and an append-only event trail — it manages intent only and never talks to a device, and never talks to the Device Registry domain either. The Auth domain (`app/domains/auth/`) implements JWT authentication and role/permission-based (RBAC) authorization for both human users and devices (agents); it is transport-independent (no FastAPI import outside `dependencies.py`/`api.py`), so the same core authenticates both REST and the WebSocket Gateway. No REST route requires authentication yet — the reusable `CurrentUser`/`CurrentDevice`/`RequireRole`/`RequirePermission` dependencies exist for future protected routes to adopt; the WebSocket Gateway's and Command Dispatcher's admin endpoints already use `RequirePermission`. An **application layer** (`app/application/`) sits between REST/WebSocket and all three domains: it is the only place a workflow spanning more than one domain is allowed to live (e.g. confirming a command's target device exists and is enabled, or confirming a device exists before issuing it a credential), the only source of the DTOs a controller ever returns, and the only translator from a domain's own exceptions into the single `ApplicationError` hierarchy REST maps to status codes (see `docs/architecture/ARCHITECTURE.md`, `docs/architecture/API.md`, `docs/architecture/DATABASE.md`, `docs/architecture/SECURITY.md`, and `docs/architecture/COMPONENTS.md`). The **WebSocket Gateway** (`app/websocket/`) implements one persistent, authenticated connection per device — transport only: it maintains sessions and delivers versioned protocol messages, and never executes a command, touches GPIO, or accesses a repository directly; its one cross-domain call is through `DeviceApplicationService` (see `docs/architecture/PROTOCOL.md`). The **Command Dispatcher** (`app/dispatcher/`) is a background service started by the FastAPI `lifespan` that discovers PENDING/QUEUED commands, delivers them to a connected device through the gateway's `SessionManager`, and tracks acknowledgement/execution — retrying transport failures with backoff and timing out a command that never produces a result — coordination only, with no command semantics or repository access of its own (see `docs/architecture/DATAFLOW.md`). Scheduler jobs, storage clients, and metrics clients remain unimplemented; their package boundaries exist solely to maintain Clean Architecture as they are introduced.

## Startup

Use Python 3.13. Create a virtual environment, install the server package with development extras, and start the factory:

```bash
python3.13 -m pip install -e '.[dev]'
make run
```

Configuration reads environment variables and a local `.env` file. Do not commit `.env`. Supported settings: `SERVER_NAME`, `ENVIRONMENT`, `LOG_LEVEL`, `HOST`, `PORT`, `DATABASE_URL`, `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_ACCESS_TOKEN_TTL_SECONDS`, `JWT_REFRESH_TOKEN_TTL_SECONDS`, `JWT_CLOCK_SKEW_SECONDS`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `VICTORIA_METRICS_URL`, `WEBSOCKET_PATH`, `WS_HEARTBEAT_INTERVAL_SECONDS`, `WS_HEARTBEAT_TIMEOUT_SECONDS`, `WS_IDLE_TIMEOUT_SECONDS`, `WS_HELLO_TIMEOUT_SECONDS`, `WS_OUTGOING_QUEUE_SIZE`, `WS_MESSAGE_ACK_TIMEOUT_SECONDS`, `WS_MESSAGE_ACK_MAX_RETRIES`, `DISPATCHER_POLL_INTERVAL_SECONDS`, `DISPATCHER_DISCOVERY_BATCH_SIZE`, `DISPATCHER_ACK_TIMEOUT_SECONDS`, `DISPATCHER_EXECUTION_TIMEOUT_SECONDS`, `DISPATCHER_MAX_RETRIES`, `DISPATCHER_RETRY_BACKOFF_BASE_SECONDS`, `DISPATCHER_RETRY_BACKOFF_MAX_SECONDS`, `DISPATCHER_SWEEP_INTERVAL_SECONDS`, and comma-separated `ALLOW_ORIGINS`. `JWT_SECRET` must be set for any Auth endpoint (or the WebSocket Gateway) to work; it is otherwise `None` and those endpoints fail safely with `503`/an authentication-failed close. The Command Dispatcher requires `DATABASE_URL` to start at all — with none configured, it stays idle and `/ready` still reports healthy (a dispatcher that never started is not a readiness failure; one that started and then stopped is).

## Development Workflow

Run `make format`, `make lint`, `make typecheck`, and `make test` before review. Install hooks with `pre-commit install`. Add new behavior through the appropriate architectural boundary and update the corresponding documentation/ADR; do not bypass the container or instantiate infrastructure in route handlers.

## Project Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | Application factory and lifespan |
| `app/config/` | Pydantic Settings configuration |
| `app/core/` | Container, shared SQLAlchemy `Base`/`Database`, and public error contracts |
| `app/api/` | HTTP delivery adapters (health, Command Dispatcher admin endpoints) |
| `app/dependencies/` | Shared FastAPI dependency providers (e.g. `get_database`, `get_event_bus`) reused across domains |
| `app/domains/devices/`, `app/domains/commands/`, `app/domains/auth/` | Implemented business domains (Device Registry, Command lifecycle, JWT auth/RBAC) |
| `app/application/` | Application layer: cross-domain orchestration, DTOs, mappers, the event bus, application exceptions, centralized validators, and future-facing interfaces |
| `app/websocket/` | The WebSocket Gateway: authenticated per-device sessions, protocol envelope/message schemas, heartbeat, backpressure, and admin `/ws/sessions` + `/metrics` endpoints (transport only) |
| `app/dispatcher/` | The Command Dispatcher: priority queue, delivery, ack/timeout/retry tracking, and result handling — started/stopped by the FastAPI lifespan (coordination only) |
| `app/logging/`, `app/middleware/` | Structured observability and request context |
| `app/{models,repositories,services,scheduler,storage,metrics}/` | Reserved architecture boundaries |
| `tests/` | Foundation tests |

## Container Development Stack

`docker compose up --build` starts the server plus PostgreSQL, VictoriaMetrics, Grafana, and MinIO. These services are intentionally not used by server application logic yet. The bundled local credentials are development-only and must never be reused outside this compose stack.
