# Pump Architecture

## Purpose

Define how the agent triggers a physical timer relay module to run the water pump, and the safety guarantees around the GPIO line that does it.

## Scope

One GPIO output line, driven by the agent, wired to a timer relay module's trigger input. The timer relay — not the Raspberry Pi — owns how long the pump actually runs.

## Design Principle: the Pi never controls watering duration

This is the one rule every other design decision here follows from: **the Raspberry Pi never controls watering duration.** It only ever generates one short GPIO pulse. A timer relay module, wired between the Pi's GPIO line and the pump itself, is what actually latches on and runs the pump for a real duration (seconds to minutes, set on the relay module's own dial/DIP switches — outside the agent's knowledge or control entirely). This is deliberate, not a missing feature:

- **Failure containment.** If the agent crashes, the process hangs, the WebSocket connection drops, or the whole Pi loses power mid-watering, the relay's own hardware timer still runs to completion (or times out) independent of the Pi. A software-driven "hold this pin high for N seconds" design would instead leave the pump running indefinitely — or stop it early — at the mercy of whatever killed the agent.
- **One command, no state machine.** Because the Pi's job ends the instant the pulse ends, there is no `pump.stop`, no "is the pump currently running" state to track and no risk of that state drifting from physical reality after a reconnect. `pump.trigger` is the only command; see [Commands](COMMANDS.md) and `server/app/domains/commands/` for how it's dispatched like any other opaque `command_type`/payload.
- **A trigger relay's real interface is a pulse, not a level.** The timer relay modules this is designed for (opto-isolated single-channel relay boards with an onboard adjustable timer) trigger on an edge or a brief level change on their input, then run their own internal timing circuit — holding the input longer than necessary changes nothing about run time, it only changes how long the Pi's own thread is blocked.

## Architecture (implemented)

`agent/app/plugins/pump/` follows the same plugin shape as `agent/app/plugins/camera/` (see [Camera](CAMERA.md) and [Agent](AGENT.md)):

| File | Owns |
| --- | --- |
| `gpio.py` | `PumpGpioPort` (the `Protocol` seam) and `LgpioPumpGpio` (the real driver). `PumpService` never imports `lgpio` directly or knows any pin-library detail — only `gpio.py` does, matching `docs/agent/GPIO.md`'s "never import GPIO libraries outside a driver adapter" rule. |
| `service.py` | `PumpService` — owns the GPIO line's safe-idle guarantee and the single-pulse trigger lifecycle: `initialize()`, `shutdown()`, `trigger()`, `status()`. |
| `metrics.py` | `pump_trigger_total`, `pump_trigger_failures_total`, `pump_trigger_duration_seconds` — process-global Prometheus objects, same pattern as `app/plugins/camera/metrics.py`. |
| `plugin.py` | `PumpPlugin` — the `on_startup`/`on_shutdown`/`check_health()` hooks that make the safety guarantees below actually run. |
| `handlers.py` | `PumpTriggerHandler` (`pump.trigger`) and `register_pump_handlers()`. |
| `exceptions.py` | `PumpUnavailableError` (GPIO hardware/driver failure) and `PumpBusyError` (a trigger was already in progress). |

### Raspberry Pi 5 and the RP1 GPIO controller

Raspberry Pi 5 moved GPIO off the SoC entirely, onto a separate southbridge chip called RP1, reached over PCIe rather than memory-mapped registers on the same die. `RPi.GPIO` — the library nearly every older Pi GPIO tutorial uses — talks to the pre-Pi-5 BCM283x GPIO controller's registers directly and has no idea RP1 exists, so it does not work on a Pi 5. `lgpio` instead goes through the kernel's `/dev/gpiochip*` character-device interface, which RP1's kernel driver exposes with the same shape every earlier Pi's GPIO controller used — this is what makes `lgpio` (and `gpiozero` configured with its lgpio pin factory, which wraps the same library) the Pi-5-compatible choice, not a library preference. `LgpioPumpGpio` (`gpio.py`) is the one file that imports `lgpio`, and does so lazily inside `open()`/`set_energized()`/`close()` — never at module import time — so the rest of the agent, including its full test suite, runs on a machine with no GPIO hardware or the `gpio` extra installed at all (`pip install -e '.[gpio]'`; see `agent/pyproject.toml`).

### Pulse triggering

`pump.trigger` is the one command. Its handler (`PumpTriggerHandler.execute`, in `handlers.py`) offloads to `PumpService.trigger()` on a thread-pool executor — the pulse's `time.sleep` is real blocking I/O, never run on the agent's asyncio event loop, exactly like `CameraService`'s frame pump. `trigger()` does exactly three things, always in this order:

1. Energize the line (`PumpGpioPort.set_energized(True)`).
2. Sleep for the pulse width — `pulse_duration_ms` from the command payload if given (validated against `PUMP_TRIGGER_PULSE_MIN_MS`/`PUMP_TRIGGER_PULSE_MAX_MS` in `PumpTriggerHandler.validate()` before it ever reaches the service), otherwise `PUMP_TRIGGER_PULSE_MS` (default 200ms).
3. De-energize the line, unconditionally, in a `finally` block — see Safety below.

The command result reports `gpio_pin`, `pulse_duration_ms`, `triggered_at`, and `duration_seconds` (wall-clock time actually spent energized, useful for spotting thread-scheduling drift against the requested pulse width). There is no `pump.status` command — `pump.trigger`'s tracked state (Idle/Triggering, last trigger time, last pulse width, total trigger count) is exposed the same way `CameraService`'s stream state is folded into the agent's existing status surface: `PumpPlugin.check_health()`, which flows into `system.health` and the aggregated `plugins` health check (`app/health/checks.py::check_plugins`) automatically — no new command was added just to expose it.

### Safety

Safety is the highest-priority property of this plugin — every other design choice here defers to it. **The output must never be left energized.**

- **Startup.** `PumpPlugin.on_startup()` (run from `PluginManager.startup()`, which `Agent.run()` calls before the agent even attempts its first connection) claims the GPIO line and immediately forces it de-energized, before anything else in the process can touch it. `PumpService.initialize()` is best-effort, the same as `shutdown()` below: a hardware/permission failure to even *open* the line (missing gpiochip, a udev/group misconfiguration, wrong chip index) is recorded in `last_error`/`check_health()` rather than raised, so it degrades only the pump capability rather than crashing agent startup entirely. `PluginManager.startup()` (`app/plugins/registry.py`) has no per-plugin error isolation — an exception propagating out of one plugin's `on_startup()` would previously take down the whole agent process, including camera and connectivity, not just the pump; see `app/tests/test_pump_plugin.py::test_on_startup_never_raises_when_gpio_cannot_be_opened`, added after exactly this happened against real hardware (the systemd service user was missing the `gpio` group — see Deployment below).
- **Shutdown.** `PumpPlugin.on_shutdown()` forces the line de-energized again and releases it. This runs from `Agent._shutdown()`, which is reached on a server-initiated `GOODBYE`, a SIGTERM/SIGINT-driven graceful stop (`app/system/signals.py` → `Agent.request_stop()`), or the run loop exiting for any other reason — there is no shutdown path that skips it. `PumpService.shutdown()` is deliberately best-effort (`try`/`except`, never raises) so a misbehaving GPIO library on the way out can never block process exit.
- **Mid-trigger exceptions.** `PumpService.trigger()`'s energize-then-sleep step is wrapped in its own `try`/`finally`, with the de-energize call in the `finally`. If `set_energized(True)` itself raises — a real GPIO write failure — the line is still forced de-energized before the exception propagates. This is the one place "never leave the output HIGH" is enforced for an in-flight pulse, and it is covered directly by `app/tests/test_pump_service.py::test_trigger_force_de_energizes_even_when_energize_itself_raises`.
- **Never a raw, polarity-blind "always drive physical LOW."** `PUMP_ACTIVE_HIGH` decides which physical level actually de-energizes the relay's trigger input — HIGH for an active-high module (the default), LOW for an active-low one. All three safety paths above call `set_energized(False)`, never a bare "write 0" — for `PUMP_ACTIVE_HIGH=false`, "safe" is physically HIGH, and getting that backwards would leave an active-low relay permanently triggered at rest, the opposite of safe. See `LgpioPumpGpio._level_for()` in `gpio.py`.

### Concurrency

Only one pulse may run at a time. `PumpService.trigger()` takes its internal lock non-blocking (`threading.Lock.acquire(blocking=False)`); a second `pump.trigger` arriving while one is already in flight is rejected immediately with `PumpBusyError`, not queued or blocked. Given a real pulse is milliseconds long, a caller can simply retry rather than the agent needing to buffer a backlog of trigger requests.

### Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `PUMP_GPIO_PIN` | `17` | The GPIO line (BCM numbering) wired to the timer relay's trigger input. |
| `PUMP_ACTIVE_HIGH` | `true` | Whether energizing the relay's trigger input means driving the line physically HIGH (`true`) or physically LOW (`false`, an active-low module). |
| `PUMP_TRIGGER_PULSE_MS` | `200` | The pulse width used when a `pump.trigger` command doesn't override it. |
| `PUMP_TRIGGER_PULSE_MIN_MS` / `PUMP_TRIGGER_PULSE_MAX_MS` | `50` / `5000` | The bounds a command-supplied `pulse_duration_ms` override must fall within (`PumpTriggerHandler.validate()`); also the bounds `PUMP_TRIGGER_PULSE_MS` itself is validated against at settings load, so a misconfigured default fails fast at startup rather than at the first trigger. |

None of this reaches the workflow/command payload as a duration parameter beyond the bounded, optional `pulse_duration_ms` override — a workflow step referencing `pump.trigger` never specifies "how long to water," since the relay, not the workflow, decides that.

### Deployment: device permissions

`/dev/gpiochip0` is owned `root:gpio` (mode `660`) on Raspberry Pi OS, the same way `/dev/media0`/`/dev/video*` are owned `root:video`. `deployment/systemd/samslab-agent.service` runs the agent as a dedicated, non-root `samslab-agent` user and grants device access the normal Unix way — via `SupplementaryGroups=` — rather than through systemd device sandboxing (see the unit file's own comment). That line must include both `video` (camera) and `gpio` (pump); confirm the actual owning group on target hardware with `ls -l /dev/gpiochip0`, since it can vary by OS image, then `systemctl daemon-reload && systemctl restart samslab-agent`. Getting this wrong doesn't fail loudly at the OS level — `lgpio.gpiochip_open()` raises a generic `'can not open gpiochip'` error covering both a missing device and a permissions failure — but it no longer crashes the agent (see Safety above): the pump plugin comes up unhealthy and every `pump.trigger` fails with `PumpUnavailableError` until the permission is fixed, while camera/connectivity/everything else keeps working.

## Design Decisions

Never import a GPIO library outside `gpio.py`'s driver adapter — `PumpService`, `PumpPlugin`, and `PumpTriggerHandler` all depend on `PumpGpioPort` only, matching the codebase-wide rule that business logic never imports hardware libraries directly. Default the output to its safe (de-energized) state during startup, error, and shutdown, per `docs/agent/GPIO.md`'s own "Design Decisions." Treat the pulse-triggering command as auditable exactly like any other: `pump.trigger` is created through the same `CommandApplicationService`/`Command` state machine as every other command, with the usual `correlation_id`/`trace_id`, so a trigger's timing is always reconstructable from the Commands domain's own history — no separate pump-specific audit log was added.

## Future Considerations

Add circuit-level interlocks (e.g. a float-switch input the pump refuses to trigger against), a configurable minimum interval between triggers (beyond the in-flight concurrency rejection this plugin already enforces), and calibration/verification hooks if a future relay module reports its own run-time back to the agent.

## Open Questions

Which specific timer relay module(s) are in scope for calibration/testing, and do any of them need a longer minimum pulse width than 50ms to reliably latch?

## References

- [Agent](AGENT.md), [GPIO](GPIO.md), [Commands](COMMANDS.md)
- [Camera](CAMERA.md) — the other implemented agent plugin, and the structural pattern this one follows
