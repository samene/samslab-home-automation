# Terminal Architecture

## Purpose

Define how an authenticated operator gets a real, fully interactive Linux shell on a device — the terminal plugin's PTY lifecycle, the wire protocol that carries it, and the browser-facing relay that makes it reachable without SSH.

## Scope

One PTY-backed shell process per device, spawned and owned by the agent, streamed byte-for-byte over the existing agent<->server WebSocket connection and relayed to a browser over a second, purpose-built WebSocket the browser opens directly to the cloud server. Not a command: see "Design Principle" below.

## Design Principle: a terminal session is a stream, not a command

Every other agent capability (`camera.*`, `pump.trigger`) is modeled as a `Command` — a one-shot request with a validated payload, an ack, and a terminal result — because that is what those operations actually are. An interactive shell is not: it is a long-lived, bidirectional byte stream with no natural "result," and forcing it through the Command Framework's ack/timeout/retry machinery (built for "did this finite operation succeed," see [Commands](COMMANDS.md)) would be the wrong abstraction, not a shortcut. So `TERMINAL_OPEN`/`TERMINAL_INPUT`/`TERMINAL_OUTPUT`/`TERMINAL_RESIZE`/`TERMINAL_CLOSE`/`TERMINAL_OPENED`/`TERMINAL_CLOSED`/`TERMINAL_ERROR` are their own first-class `MessageType`s on the same envelope transport (`shared/protocol/`), registered directly on the agent's `MessageDispatcher` and handled directly by `server/app/websocket/handlers.py`/`server/app/terminal/` — never a `command_type`, never touching `app/commands/` or the Command Dispatcher at all.

## Architecture (implemented)

The full path is: browser → a second, browser-facing WebSocket the cloud server terminates (`server/app/terminal/`) → the *existing* agent<->server WebSocket Gateway (`server/app/websocket/`, unmodified in its own responsibilities, just carrying more message types) → the agent's `TerminalService`, which owns a real PTY and shell process. The browser never talks to the Raspberry Pi directly, matching the same rule Camera and every other capability already follow.

### Agent (`agent/app/plugins/terminal/`)

| File | Owns |
| --- | --- |
| `pty_process.py` | The only file that touches `pty`/`fcntl`/`termios`/`subprocess` directly: `spawn_pty()`, `resize_pty()`, `terminate_pty()`. |
| `service.py` | `TerminalService` — the session dictionary, the `MessageDispatcher`-registered handlers (`handle_open`/`handle_input`/`handle_resize`/`handle_close`), the non-blocking read/write loop, and the idle-timeout watchdog. |
| `plugin.py` | `TerminalPlugin` — starts the watchdog on agent startup, terminates every open session on agent shutdown, folds session count into plugin health. |
| `metrics.py` | `terminal_sessions_active`/`_opened_total`/`_closed_total`/`_session_errors_total` — the same process-global `prometheus_client` pattern every other plugin uses. |

**Spawning**, deliberately not `pty.fork()`: this agent is a multi-threaded asyncio process (the camera plugin alone runs its frame pump on a background thread), and `fork()` in a multi-threaded process only carries the forking thread into the child — a lock another thread held at fork time can deadlock the child forever. `spawn_pty()` instead uses `pty.openpty()` + `subprocess.Popen(..., start_new_session=True)`: `start_new_session` does the equivalent `setsid()` safely in C, before any Python re-enters the forked child, avoiding both the fork-in-threads hazard and the further hazard of a `preexec_fn` (arbitrary Python running post-fork, which the stdlib's own `subprocess` docs warn against in a threaded program). The shell still ends up a session/process-group leader with the PTY slave as its controlling terminal — full job control (Ctrl+C, Ctrl+Z), and full-screen programs (`vim`, `top`, `less`) all work exactly as they would over SSH, because it *is* a real controlling TTY, not an emulation of one.

**Streaming, not polling.** The master fd is set non-blocking and registered with `loop.add_reader()`; every readable wakeup does one `os.read()` and immediately schedules a `TERMINAL_OUTPUT` envelope — no buffering, no fixed poll interval. Writing (`TERMINAL_INPUT`) is the mirror: `os.write()` first, and only the rare `BlockingIOError` (a full kernel PTY buffer, realistic only for a very large paste) falls back to `loop.add_writer()` to drain the remainder once the fd is writable again. This is what makes `tail -f`, `top`, `watch`, `vim`, and a Python REPL all work — every one of them is just a program that reads/writes its controlling TTY, which is exactly what's wired up here, nothing interactive-program-specific was implemented.

**Resize.** `TERMINAL_RESIZE` calls `resize_pty()`, which is `fcntl.ioctl(master_fd, termios.TIOCSWINSZ, ...)` — the kernel delivers `SIGWINCH` to the foreground process group on its own; nothing in this codebase sends that signal itself. On the browser side, xterm.js's own `onResize` (fired by its `FitAddon` reacting to the drawer's size) is the one place a resize is triggered from — see Frontend below.

**Session identity and reuse.** `TERMINAL_OPEN` carries a `session_id`; if one is already tracked, `handle_open` treats it as an attach/reuse (replies `TERMINAL_OPENED` again, spawns nothing new) rather than a second shell for the same ID — this is what "one active session per device, reuse if appropriate" means concretely. `TERMINAL_MAX_SESSIONS_PER_DEVICE` (default `1`) bounds how many *distinct* session IDs may be open at once, rejecting a genuinely new one past that cap with `TERMINAL_ERROR{code="max_sessions_reached"}` rather than queuing it.

**Lifecycle and zombie prevention.** `terminate_pty()` signals the whole process *group* (`os.killpg`, SIGTERM then SIGKILL after a bounded wait), not just the shell's own pid — a foreground child the shell spawned (e.g. `vim`) would otherwise be able to outlive its parent. EOF on the master fd (every fd referencing the slave closed — the shell exited) is detected the same way a clean close is, and reported as `TERMINAL_CLOSED{reason="shell_exited"}`. A watchdog task (`TerminalService._watchdog_loop`, 5s cadence) closes any session whose `TERMINAL_INPUT`/`TERMINAL_RESIZE` has been quiet longer than `TERMINAL_SESSION_TIMEOUT` — the backstop for a browser tab, network path, or whole laptop that vanishes without ever sending `TERMINAL_CLOSE`. `TerminalPlugin.on_shutdown()` terminates every still-open session as part of normal agent shutdown, the same guarantee `PumpPlugin`/`CameraPlugin` give their own hardware.

**Agent disconnect must never leave the server thinking a dead session is still open.** Two independent layers guarantee this, because either one alone is incomplete:

1. **Graceful shutdown.** `Agent._shutdown()` (`agent/app/lifecycle/orchestrator.py`) runs `plugin_manager.shutdown()` — which is what sends a final `TERMINAL_CLOSED` for every open session — *before* `connection_manager.disconnect()`, not after. This ordering is load-bearing: `TerminalService`'s own send is wrapped in a broad `except`, so sending it after the connection is already gone doesn't raise, it just silently does nothing — the server would never learn the session ended and would keep treating it as open indefinitely, since nothing else ever revisits it. (Camera/pump shutdown only release local hardware and never needed the connection, which is why this ordering bug didn't affect them and went unnoticed until the terminal plugin needed the connection to still be alive during shutdown.)
2. **Anything else** — a crash, `kill -9`, a lost network path, or (belt-and-suspenders) a graceful shutdown that still somehow loses that race. There is no message to receive in these cases, so the server can't rely on one. Instead, `server/app/terminal/relay.py` subscribes to the *existing* `DeviceHeartbeat` event the WebSocket Gateway already publishes unconditionally on every agent disconnect (`gateway.py`'s `_mark_offline_best_effort`, called from its `finally` block regardless of why the connection ended) and, on `status == "OFFLINE"`, calls `TerminalSessionManager.force_clear(device_id)` — clearing whatever session is tracked without needing to know its ID — and pushes a synthesized `TERMINAL_CLOSED{reason="agent_disconnected"}` to every browser that was attached. This is the same reasoning as `CommandService.reconcile_interrupted_commands()`/`WorkflowService.reconcile_interrupted_runs()`: a tracker that lives only in a process's memory must have an independent way to notice that process is gone, not just trust a message from it that may never arrive.

### Server (`server/app/terminal/` + `server/app/websocket/`)

The *existing* agent-facing gateway (`server/app/websocket/`) is extended, not duplicated: `handlers.py` gained four branches (`TERMINAL_OPENED`/`TERMINAL_OUTPUT`/`TERMINAL_CLOSED`/`TERMINAL_ERROR`, all *received from* the agent) that publish `Terminal*Received` events on the shared `EventBus` — the same one-way notification seam `CommandAckReceived`/`CommandResultReceived` already use, so the gateway still never imports or knows about the terminal package. `TERMINAL_OUTPUT` deliberately receives no `MESSAGE_ACK` (see `shared/protocol/message_types.TERMINAL_MESSAGE_TYPES`): it is a high-frequency byte stream where transport-level ack/retry would add latency and out-of-order-redelivery risk for no benefit, exactly like `PING`/`PONG` already forgo it.

`server/app/terminal/` is a new, coordination-only package — the same shape as `server/app/dispatcher/`, not a domain (no persistence; every session lives only in memory, dropped on restart like every WebSocket session already is):

| File | Owns |
| --- | --- |
| `router.py` | `TerminalGateway` — the browser-facing `WS /ws/terminal/{device_id}` endpoint's full connection lifecycle: accept, HELLO-style handshake, relay browser→agent messages via the *existing* `SessionManager.send()`. |
| `manager.py` | `TerminalSessionManager` — an in-memory `device_id -> (session_id, shell, {attached browsers})` registry; the "reuse an existing session" and "broadcast to every attached tab" logic lives here. |
| `connection.py` | `BrowserConnection` — a deliberately smaller sibling of `app/websocket/connection.py`'s `Connection`: just the bounded outgoing queue + backpressure half, no ack-tracking or duplicate detection (this leg doesn't need either — see above). |
| `relay.py` | `register_terminal_relay()` — subscribes to the four `Terminal*Received` events once per application (like `register_notification_subscribers`) and broadcasts each to every browser currently attached to that device. |

**Authentication, not a new model.** The browser cannot set a custom `Authorization` header on a native `WebSocket` handshake, so — mirroring exactly how the agent gateway itself solves "authenticate before the first real message" — the browser's first frame must be a normal `HELLO` (the same `HelloPayload`/`decode_principal()` REST and the agent gateway both already use), just carrying a **user** JWT instead of a device one. `TerminalGateway._handshake()` requires `PrincipalType.USER` and `"commands.execute" in principal.permissions` — the identical permission REST's own command-creation endpoints require, not a new terminal-specific one — then confirms the target device exists, is enabled, and currently has an open agent session (`SessionManager.get(device_id)`) before ever forwarding anything. This is the literal "only reuse existing auth" instruction: no new token type, no query-string credential, no separate mint endpoint.

**Multi-tab reuse.** A second browser attaching to a device with an already-open session does not send a second `TERMINAL_OPEN` to the agent — `TerminalSessionManager.attach()` returns the existing session ID, and the new browser gets a synthesized `TERMINAL_OPENED` (or, if the agent's own confirmation is still in flight, just waits for `relay.py`'s broadcast like every other attached tab).

## Protocol

See [Components](COMPONENTS.md) and [Protocol](PROTOCOL.md) for the full envelope shape and the complete `Terminal*Payload` schemas (`shared/protocol/schemas.py`). Summary:

| Type | Sender | Purpose |
| --- | --- | --- |
| `TERMINAL_OPEN` | browser → server → agent | Open (or attach to) one PTY session; carries `session_id`, `cols`, `rows`. |
| `TERMINAL_OPENED` | agent → server → browser | Confirms the session is open and ready; carries the shell path. |
| `TERMINAL_INPUT` | browser → server → agent | Raw keystroke/paste bytes, UTF-8 text on the wire. |
| `TERMINAL_OUTPUT` | agent → server → browser | Raw PTY output bytes, streamed as produced. |
| `TERMINAL_RESIZE` | browser → server → agent | A new `cols`/`rows`. |
| `TERMINAL_CLOSE` | browser → server → agent | Explicitly terminate the session. |
| `TERMINAL_CLOSED` | agent → server → browser | The session ended; carries `reason` and, if known, `exit_code`. |
| `TERMINAL_ERROR` | agent → server → browser | A session-scoped error (disabled, spawn failure, max sessions) that doesn't necessarily close an existing session. |

## Frontend (`frontend/src/lib/terminal/`, `frontend/src/hooks/useTerminal.ts`, `frontend/src/components/terminal/`)

`TerminalService` (a plain WebSocket client class, no framework dependency) owns one browser-side connection: HELLO on open, `TERMINAL_OPEN` once `WELCOME` arrives, callbacks for output/opened/closed/error, and reconnect-with-backoff on an unexpected close. `useTerminal(deviceId, active)` wires one `@xterm/xterm` `Terminal` instance (with `@xterm/addon-fit`, `@xterm/addon-web-links`, `@xterm/addon-search` loaded) to one `TerminalService`: `term.onData` → `sendInput`, `term.onResize` (fired by `FitAddon` reacting to a `ResizeObserver` on the host element) → `resize`, and the service's `onOutput` → `term.write`. Because this is a *real* PTY and a *real* xterm.js instance, Ctrl+C/Ctrl+L/arrow keys/Tab completion/Home/End/Delete/function keys all work with zero special-case code — xterm.js already encodes the correct escape sequence for each key, and a real shell already knows what to do with it; this is the direct payoff of not building a custom line-oriented command box.

`TerminalDrawer` is a resizable bottom sheet (built on the same `Sheet`/Radix Dialog primitive the mobile nav uses) that mounts `TerminalPanel` only while open. This is deliberate, not a limitation: Radix unmounts `SheetContent`'s children on close, which tears down this browser's WebSocket/xterm.js instance — but the PTY session itself lives on the agent and is untouched by that, per "one active session per device, reuse if appropriate" above. Reopening the drawer opens a fresh WebSocket that reattaches to the same still-alive session: `cd`, environment variables, shell history, and any running program all survive; only the xterm.js scrollback buffer itself resets, since that lives in the browser, not the shell. The drawer's own close button, and collapsing it, are the same "not the real end of the session" action — a distinct "Terminate session" control in `TerminalToolbar` is what actually sends `TERMINAL_CLOSE`.

`frontend/README.md`'s "Live updates: polling, not a browser WebSocket" note is deliberately **not** violated by accident here — see its own updated text: this is the one, explicitly-scoped exception, because an interactive shell fundamentally needs a real duplex low-latency stream that polling cannot provide, and it is authenticated exactly the way that note says a real one would have to be.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `TERMINAL_ENABLED` (agent) | `false` | Off by default so a fresh deployment doesn't expose a shell until an operator deliberately opts in — checked again on every `TERMINAL_OPEN`, independent of the server-side permission check. |
| `TERMINAL_SHELL` (agent) | `/bin/bash` | The shell spawned for every session. |
| `TERMINAL_SESSION_TIMEOUT` (agent) | `300` (seconds) | Idle-input timeout enforced by the watchdog; resets on every `TERMINAL_INPUT`/`TERMINAL_RESIZE`. |
| `TERMINAL_MAX_SESSIONS_PER_DEVICE` (agent) | `1` | Cap on concurrent *distinct* session IDs (not attached browsers — see multi-tab reuse above). |
| `TERMINAL_WEBSOCKET_PATH` (server) | `/ws/terminal` | The browser-facing route prefix; `{device_id}` is appended by `server/app/terminal/router.py`. |

## Design Decisions

Never model a persistent stream as a `Command` just because every other capability is one — see "Design Principle" above; this is the one place in the codebase that deliberately does not follow the Command Framework, and the reason is structural, not a shortcut. Reuse the existing `HelloPayload`/`decode_principal()`/`RequirePermission`-equivalent authentication primitives for the browser leg rather than inventing a scoped terminal token, matching how `docs/architecture/SECURITY.md`/`PROTOCOL.md` already describe `decode_principal()` as transport-independent and reusable by a future transport. Exclude `TERMINAL_INPUT`/`TERMINAL_OUTPUT` from transport-level ack/retry (`ACK_REQUIRED_MESSAGE_TYPES`) for the same reason `PING`/`PONG` are excluded: a high-frequency stream, not a discrete delivery. Prefer `pty.openpty()` + `subprocess.Popen(start_new_session=True)` over `pty.fork()` given this agent's multi-threaded runtime — see Agent/Spawning above.

## Future Considerations

A wire-level capability flag (advertised in `HELLO.capabilities`) so the server/UI can know a given agent build actually supports the terminal plugin before offering the button, rather than only discovering `TERMINAL_ERROR{code="terminal_disabled"}` after trying. Server-side output buffering/replay so a browser reattaching to an already-open session sees recent scrollback instead of a blank screen. A `TERMINAL_RESIZE` rate limit if a pathological client resizes far faster than any real UI would.

## Open Questions

Should `TERMINAL_SHELL` support per-user overrides (e.g. a restricted shell for a lower-privileged role) once the RBAC model grows beyond today's single `commands.execute` gate?

## References

- [Agent](AGENT.md), [Commands](COMMANDS.md)
- [Camera](CAMERA.md), [Pump](PUMP.md) — the Command-based plugins this one deliberately does *not* follow the shape of, and why
- [Protocol](../architecture/PROTOCOL.md), [Components](../architecture/COMPONENTS.md), [Security](../architecture/SECURITY.md)
