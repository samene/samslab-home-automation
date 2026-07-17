# Release Process

## Purpose

Define reliable, reversible releases for server and edge agent artifacts.

## Scope

Versioning, verification, deployment, rollback, and communication.

## Architecture

Use Semantic Versioning: major for incompatible public protocol/API changes, minor for backward-compatible capability, patch for fixes. Build versioned immutable artifacts from reviewed commits. Before release, run checks, protocol compatibility tests, migration review, security scan, backup verification, and deployment rehearsal appropriate to risk. Record release notes, included ADRs, compatibility, migrations, and rollback steps.

Deploy server changes with controlled migrations and health/metric checks. Deploy agent changes in a staged ring, verify reconnect, driver health, and spool behavior, then expand. Roll back artifacts when safe; database changes require preplanned forward-fix/restore procedures.

## Design Decisions

Protocol compatibility and observability are release gates. Secrets are rotated separately from normal artifact promotion. Never deploy an untested change directly to essential actuator hardware.

## Future Considerations

Automated changelogs, signed artifacts, canaries, and fleet rollout controls.

## Open Questions

What release cadence and maintenance window suit the home environment?

## References

- [Deployment](../architecture/DEPLOYMENT.md)
- [Testing](TESTING.md)
