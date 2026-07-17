# GPIO Architecture

## Purpose

Define safe, testable GPIO control boundaries.

## Scope

Relays, LEDs, pumps, and future digital/analog hardware connected through the Pi or supported bridges.

## Architecture

Business services express desired operations through typed driver ports; GPIO adapters alone map them to pin libraries and board configuration. Device definitions include stable logical IDs, pin mapping, polarity, safe startup state, allowed operation, timeout, and interlock requirements. Driver fakes support tests without hardware.

## Design Decisions

Never import GPIO libraries outside a driver adapter. Default outputs to safe states during startup, error, and shutdown. Validate pin conflicts and capability ownership before activation; treat power-switching operations as safety-sensitive commands with audit records.

## Future Considerations

Add circuit-level interlocks, watchdogs, ADC/ESP32 adapters, calibration records, and hardware simulation.

## Open Questions

Which relay boards, voltage domains, and emergency-stop controls are in scope first?

## References

- [Agent](AGENT.md)
- [Commands](COMMANDS.md)
