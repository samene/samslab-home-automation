# Contributing

## Purpose

Explain how changes remain coherent, safe, and reviewable.

## Scope

All documentation, application, infrastructure, and operational contributions.

## Architecture

Start by reading the relevant architecture/agent documentation and ADRs. Make a focused change on a branch, preserve dependency direction, add tests and documentation, run formatting/lint/type/test checks once configured, and submit a reviewable pull request. Use Conventional Commits such as `feat(agent): add sensor driver` or `docs: clarify command retry policy`.

## Design Decisions

No contribution may bypass repositories, access GPIO outside drivers, give the agent PostgreSQL access, hard-code secrets, or introduce untyped boundary data. Material architecture changes require an ADR before implementation. Review checks security, failure recovery, observability, and offline behavior alongside correctness.

## Future Considerations

Add PR templates, code owners, automated checks, and contributor onboarding after initial tooling exists.

## Open Questions

What review quorum is required for security-sensitive production changes?

## References

- [Copilot instructions](../../.github/copilot-instructions.md)
- [ADR process](../architecture/ADR.md)
