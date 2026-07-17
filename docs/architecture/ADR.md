# Architecture Decision Records

## Purpose

Provide a durable, reviewable record of significant architectural decisions.

## Scope

Applies to decisions affecting interfaces, security, persistence, operations, or future extensibility.

## Architecture

Store one immutable record per decision under `docs/architecture/adr/` when implementation begins. Name files `NNNN-short-title.md` and use: Status, Context, Decision, Consequences, Alternatives Considered, and References. Supersede decisions with a new ADR; do not rewrite history.

Initial decisions to record: outbound-only agent connectivity; WebSocket control channel; PostgreSQL server ownership; SQLite offline outbox; S3 binary storage; Clean Architecture with dependency injection; protocol versioning; observability baseline.

## Design Decisions

ADRs are required before materially changing a boundary. Accepted ADRs guide code and documentation; proposed ADRs are not implementation authorization.

## Future Considerations

Use lightweight review metadata and link ADRs from pull requests and releases.

## Open Questions

Who approves decisions affecting security or operational cost?

## References

- [Architecture](ARCHITECTURE.md)
- [Contributing](../development/CONTRIBUTING.md)
