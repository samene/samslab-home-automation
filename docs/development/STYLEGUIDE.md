# Development Style Guide

## Purpose

Set consistent, maintainable standards for future Python implementation.

## Scope

Applies to all production code, tests, scripts, configuration, and documentation.

## Architecture

Target a currently supported Python 3 release, pinned before implementation and consistent across server and agent. Use explicit type hints, typed Pydantic models at boundaries, async APIs for networking, dependency injection at composition roots, and package organization by architectural layer rather than framework convenience. Domain types and services remain independent of transport, database, and hardware packages.

## Design Decisions

Use an automated formatter, linter, type checker, and test runner selected and configured before first code. Naming: `snake_case` for functions/variables/modules, `PascalCase` for types, `UPPER_SNAKE_CASE` for constants, descriptive UUID-based identifiers, and verbs for command operations. Keep functions small, use composition, avoid global state, document public contracts, and write structured logs without secrets.

## Future Considerations

Adopt import-boundary checks and generated API/protocol documentation when package structure exists.

## Open Questions

Which exact Python version and toolchain versions will be pinned?

## References

- [Architecture](../architecture/ARCHITECTURE.md)
- [Testing](TESTING.md)
