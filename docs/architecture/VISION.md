# Vision

## Purpose

Capture the enduring product direction for Sam's Lab.

## Scope

Sam's Lab begins as a personal home automation platform centered on a Raspberry Pi 5 and grows into a modular, secure multi-agent system.

## Architecture

The platform separates a cloud control plane from offline-capable edge agents. It uses typed commands, pluggable drivers, durable local synchronization, and server-owned metadata/storage services.

## Design Decisions

Prioritize safety, operability, privacy, and expansion over one-off hardware shortcuts. New hardware enters through drivers and shared protocol contracts.

## Future Considerations

Support multiple Raspberry Pis, ESP32 devices, sensors, pumps, lighting, cameras, schedules, and automation rules without redesigning core boundaries.

## Open Questions

Which home workflows should define the first product milestone?

## References

- [Architecture](ARCHITECTURE.md)
- [Roadmap](../development/ROADMAP.md)
