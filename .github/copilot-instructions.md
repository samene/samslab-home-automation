# Sam's Lab coding instructions

Treat this repository as a production IoT platform. Preserve its Clean Architecture boundaries: domain and application services must not import FastAPI, SQLAlchemy, GPIO libraries, WebSocket clients, or cloud SDKs. Use dependency injection; do not introduce global mutable state or service locators.

- Keep persistence behind typed repository interfaces. Never bypass repositories from services or delivery code.
- The agent must never access PostgreSQL. It communicates with the server only through the authenticated, versioned WebSocket protocol and object-storage upload flow approved by the server.
- Access GPIO, cameras, serial buses, and other hardware only through driver adapters. Business logic must not import or call hardware libraries.
- Make network I/O async. Keep blocking hardware work isolated behind explicit adapters/executors.
- Use Python type hints everywhere and typed Pydantic models for every API, WebSocket, configuration, and persistence boundary.
- Model all agent requests as commands with UUIDs, timestamps, status, idempotency behavior, and typed payload/result models.
- Prefer composition over inheritance. Keep functions narrow, deterministic where possible, and explicit about failures.
- Add or update tests for every behavior change, including failure and offline/retry paths. Do not leave untested production paths.
- Emit structured JSON logs and metrics at service boundaries. Propagate correlation and request IDs; never log credentials, tokens, or sensitive media metadata.
- Read and follow `docs/architecture/` and `docs/agent/` before changing a boundary. Update ADRs and documentation when a design decision changes.
- Keep secrets out of source control. Use validated environment-based configuration and least-privilege credentials.
- Produce complete, reviewable changes; do not add placeholder implementations that silently bypass policy or safety checks.
