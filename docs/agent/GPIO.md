# GPIO Architecture

## Purpose

Define safe, testable GPIO control boundaries.

## Scope

Relays, LEDs, pumps, and future digital/analog hardware connected through the Pi or supported bridges.

## Architecture

Business services express desired operations through typed driver ports; GPIO adapters alone map them to pin libraries and board configuration. Device definitions include stable logical IDs, pin mapping, polarity, safe startup state, allowed operation, timeout, and interlock requirements. Driver fakes support tests without hardware.

### Pump plugin (implemented)

`agent/app/plugins/pump/` is the first real GPIO driver built on this architecture — a single output line pulsed to trigger a timer relay module, never used to control watering duration itself. `PumpGpioPort` (`app/plugins/pump/gpio.py`) is the typed driver port; `LgpioPumpGpio` is its one real implementation, built on `lgpio` (not `RPi.GPIO`, which cannot see the Pi 5's RP1 GPIO controller at all — see below). See [Pump](PUMP.md) for the full design, safety guarantees, and configuration.

### Raspberry Pi 5 / RP1

Pi 5 moved GPIO off the SoC and onto a separate RP1 southbridge chip reached over PCIe, exposed to userspace through the kernel's `/dev/gpiochip*` character-device interface rather than memory-mapped registers. `RPi.GPIO` talks to the older BCM283x register layout directly and does not work on a Pi 5; `lgpio` (and `gpiozero` configured with its lgpio pin factory) goes through `/dev/gpiochip*` instead, which is what makes it the Pi-5-compatible choice for every GPIO adapter in this codebase, not a library preference.

## Design Decisions

Never import GPIO libraries outside a driver adapter. Default outputs to safe states during startup, error, and shutdown. Validate pin conflicts and capability ownership before activation; treat power-switching operations as safety-sensitive commands with audit records.

## Future Considerations

Add circuit-level interlocks, watchdogs, ADC/ESP32 adapters, calibration records, and hardware simulation.

## Open Questions

Which relay boards, voltage domains, and emergency-stop controls are in scope first?

## References

- [Agent](AGENT.md)
- [Commands](COMMANDS.md)
- [Pump](PUMP.md)
