# Edge and Object Storage

## Purpose

Define durable local state and large-file storage responsibilities.

## Scope

Agent SQLite/spool and server-authorized S3-compatible object storage.

## Architecture

SQLite holds pending events, command responses, upload records, replay cursor, and bounded local metadata cache. A filesystem spool holds media/backup artifacts with state, checksum, attempt count, creation time, and retention deadline. The server grants short-lived, least-privilege upload authorization and records object metadata after validation; PostgreSQL never stores large binary blobs.

## Design Decisions

Writes are atomic and durable before acknowledgement. Replay is ordered and deduplicated by message/command ID. Enforce quota, age, and priority policies; a full spool raises observable degradation rather than silently dropping critical command results.

## Future Considerations

Resumable multipart uploads, encryption at rest, content-addressing, remote restore, and differentiated retention tiers.

## Open Questions

What are the maximum spool size and eviction priority for the Pi's storage medium?

## References

- [Database](../architecture/DATABASE.md)
- [Camera](CAMERA.md)
