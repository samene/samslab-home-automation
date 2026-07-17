# Testing Strategy

## Purpose

Define evidence required to safely evolve Sam's Lab.

## Scope

Unit, integration, contract, hardware-adapter, resilience, and operational tests.

## Architecture

Unit-test domain and service behavior with fakes for repositories, clocks, transports, and drivers. Integration-test PostgreSQL repositories, SQLite outbox behavior, object-storage adapter interactions, REST/WebSocket delivery boundaries, and migrations in isolated environments. Contract-test shared Pydantic protocol models and version negotiation. Test drivers with fakes by default and controlled hardware-in-the-loop suites where needed.

Critical scenarios include duplicate commands, reconnect/replay, malformed frames, token rotation, clock/expiry behavior, spool exhaustion, upload interruption, safe GPIO startup/shutdown, authorization denial, and migration/restore. Tests are deterministic, hermetic where practical, and run in CI before release.

**End-to-end verification (implemented)** — `tests/integration/`, `tests/e2e/`, and `tests/load/` exercise the full REST → command creation → database → dispatcher → WebSocket Gateway → agent → command runtime → result → database pipeline against a real running server and a real (fake but protocol-conformant) agent, no hardware and no mocked transport. See [Integration & End-to-End Testing](INTEGRATION_TESTING.md) for how to run it, failure injection, and debugging.

## Design Decisions

Every behavior change includes focused tests; tests must verify failure paths, not merely happy paths. Production credentials and real home hardware are never CI prerequisites.

## Future Considerations

Add property-based protocol tests, security scans, and a hardware staging rig. Fault injection and load tests now exist for the server/agent-protocol boundary (see above) — extending fault injection to the TCP level, and load testing at larger scale with a dedicated tool, remain open.

## Open Questions

What minimum coverage and release-gate thresholds provide useful confidence without gaming metrics?

## References

- [Style guide](STYLEGUIDE.md)
- [Integration & End-to-End Testing](INTEGRATION_TESTING.md)
- [Commands](../agent/COMMANDS.md)
