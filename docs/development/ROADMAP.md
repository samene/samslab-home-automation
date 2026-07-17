# Roadmap

## Purpose

Sequence delivery while preserving architectural foundations.

## Scope

Planning guidance; it is not a release commitment.

## Architecture

1. Foundation: pin Python/tooling, create package boundaries, configuration, CI, and initial ADRs.
2. Shared contracts: versioned protocol models and command lifecycle tests.
3. Server core: identity, repositories, command orchestration, API/WebSocket session manager, migrations.
4. Agent core: systemd packaging, SQLite outbox, reconnect/heartbeat, driver registry, metrics.
5. First devices: safe GPIO relay/LED, sensor read, camera capture and authorized upload.
6. Operations: dashboards, backup/restore, alerts, security hardening, release automation.
7. Expansion: schedules/rules, ESP32 bridge, multi-agent sites, managed updates.

## Design Decisions

Each phase exits only with documented interfaces, tests, observability, and an ADR for material tradeoffs. Hardware capability is added through drivers and commands, not special-case server logic.

## Future Considerations

Prioritize by safety, owner value, and operational evidence rather than feature count.

## Open Questions

Which first device proves the vertical slice: relay, sensor, or camera?

## References

- [Architecture](../architecture/ARCHITECTURE.md)
- [Release process](RELEASE.md)
