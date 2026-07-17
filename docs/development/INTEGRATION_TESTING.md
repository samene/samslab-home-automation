# Integration & End-to-End Testing

## Purpose

Verify the whole distributed system — REST API, command creation, database
persistence, the Command Dispatcher, the WebSocket Gateway, an agent, the
command runtime, and the resulting database update — works correctly
together, without any hardware and without mocking the WebSocket transport.

## Scope

`tests/integration/`, `tests/e2e/`, `tests/load/`, and their shared
infrastructure (`tests/utils/`, `tests/fakes/`, `tests/fixtures/`), plus the
developer CLI at `examples/verify_system.py`. Distinct from `server/tests/`
(fast, isolated unit/integration tests scoped to one process, some of which
already exercise the dispatcher against an in-process duck-typed fake agent —
see `server/tests/test_dispatcher_integration.py`) and from `agent/app/tests/`
(the agent's own unit tests). This framework is the only place a real socket
connects a real WebSocket client to a real running server.

## Architecture

### Why a separate framework, and why real sockets

`agent/` and `server/` are separate installable Python packages that both
happen to use the top-level import name `app` — Phase 1 established that they
must never both be on `sys.path` in the same process (see `CLAUDE.md`'s
"`app.*` namespace collision problem"). A `FakeAgent` that imported the real
agent's `agent/app/connection/` internals would force exactly that collision
into this framework's own test process.

The fix is also what "connect exactly like a Raspberry Pi" and "no mocking of
the WebSocket transport" call for anyway: `tests/fakes/fake_agent.py`'s
`FakeAgent` is a self-contained protocol-level client, built only on
`shared/protocol/` (the same wire-format package the real agent depends on)
and the third-party `websockets` client library — never on `agent/app/`
itself. It dials a real `ws://` URL, completes a real HELLO/WELCOME handshake,
and implements exactly the four `system.*` command types the real agent's
Phase 2 built-in handlers implement, nothing else. This makes `FakeAgent` a
true black-box test double: it verifies the *server's* conformance to the
wire protocol, the same way any real, non-Python agent implementation would
have to.

The server side of the equation, `tests/utils/server_harness.py`'s
`run_server()`, is a real `uvicorn.Server` bound to a real, OS-assigned
localhost TCP port, running the actual `create_app()` FastAPI application
(the real container, the real Command Dispatcher, the real WebSocket
Gateway) against a fresh, file-backed SQLite database — inside the test
process's own event loop (no subprocess, no IPC), so it's fast, but every
byte between `FakeAgent` and the server crosses a real socket.

### Running the tests

```bash
pytest tests/integration          # ~35 tests, a few seconds
pytest tests/e2e                  # the 4 documented scenarios
pytest tests/load                 # heavier concurrent load, ~20s
pytest tests/integration tests/e2e tests/load   # everything in this framework
pytest -m load                    # only the load tests, in isolation
pytest -m "not load"              # everything except the load tests
```

These run as part of the normal `pytest`/`make test` invocation from the repo
root (`testpaths` in the root `pyproject.toml` includes `tests/` alongside
`server/tests/`) — no separate command or CI job is required. `make lint`,
`make format`, and `make typecheck` all cover `tests/` and `examples/` too.

For a human-readable, no-pytest-required demo:

```bash
python examples/verify_system.py            # quiet: only this script's own output
python examples/verify_system.py --verbose  # also show the server's structured logs
```

### Expected output

A healthy `verify_system.py` run looks like:

```
Sam's Lab — System Verification
===============================
[1/4] Started server at http://127.0.0.1:PORT (0.15s)
[2/4] Registered device <uuid> (0.03s)
[3/4] Connected fake agent, session <uuid> (0.02s)
[4/4] Submitting commands:
      [OK  ] system.echo              94.0ms  status=COMPLETED
             lifecycle: COMMAND_CREATED -> COMMAND_DISPATCHED -> COMMAND_STARTED -> COMMAND_COMPLETED
      ... (system.ping, system.capabilities, system.health)

Summary
=======
4 command(s) submitted in 0.45s total
Dispatcher statistics: dispatched=4, retries=0, timeouts=0

Result: PASS — the whole system verified end to end.
```

Exit code `0` means every command reached `COMPLETED`; `1` means at least one
did not (printed as `[FAIL]` with its last known status) — script exit code
matches what CI should treat as pass/fail.

### The server harness and observability helpers

`ServerHarness` (`tests/utils/server_harness.py`) is the one object most
tests interact with:

| Method | What it exercises |
| --- | --- |
| `register_device()` / `create_command()` | The real `POST /devices` / `POST /commands` REST endpoints |
| `get_device()` / `get_command()` | The real `GET` endpoints — this is how a test verifies database persistence |
| `issue_device_token()` / `issue_user_token()` | Real, signed JWTs via the real `JWTCodec` — no login flow needed for a test double |
| `dispatcher_status/queue/running/statistics()` | The admin `/dispatcher/*` endpoints (`RequirePermission("system.admin")`, hence `issue_user_token()`) |
| `sessions()` / `session_for()` | The admin `/ws/sessions` endpoints |
| `metrics_text()` | The real `/metrics` Prometheus endpoint |
| `health()` / `readiness()` | `/health` and `/ready` |

`tests/utils/waiters.py` provides `wait_for_command_status`,
`wait_for_device_status`, `wait_for_session`, `wait_for_no_session`, and
`wait_for_message` (for polling a connected `FakeAgent`'s own `received`
list) — every real round trip (dispatch, ack, execution, a DB write) takes
real wall-clock time, so these poll with a timeout rather than a fixed
`sleep()` then assert, which is both faster on a healthy run and not flaky
under load.

`tests/utils/metrics.py`'s `metric_value(text, name, **labels)` parses the
real Prometheus text format (via `prometheus_client.parser`, not a hand-rolled
parser) and returns one sample's value. **Only server-side metrics are
observable here** — `connected_devices`, `messages_sent_total`/
`messages_received_total` (`app/websocket/metrics.py`), and
`commands_dispatched_total`/`dispatcher_retries_total`/
`dispatcher_timeouts_total`/etc. (`app/dispatcher/metrics.py`). The *agent's*
own metrics (`commands_received_total`, `heartbeat_total`, and the rest of
`agent/app/commands/metrics.py`/`agent/app/metrics/registry.py`) only exist
inside a real running `agent/` process — `FakeAgent` doesn't run that code at
all, by design (see above), so they're never present on this server's
`/metrics` output.

`tests/utils/logs.py`'s `LogCapture` redirects `sys.stdout` to an in-memory
buffer for the duration of a `with` block, parses each line as one structured
JSON log event, and exposes `events()`/`events_matching(**fields)`. It must be
entered *before* `run_server()` starts — `configure_logging()` binds
`logging.basicConfig(stream=sys.stdout, ...)` once, at that moment, so
`LogCapture` needs to already be the active `sys.stdout` by then. See
`tests/e2e/test_scenario_1_echo_roundtrip.py` for the canonical pattern, and
verify server-side log events carry `correlation_id`/`request_id` (REST) or
`device_id`/`connection_id` (WebSocket) — the agent-side `command_id`/
`trace_id` fields are, again, only emitted by a real `agent/` process.

### Failure injection

`FakeAgent` carries opt-in knobs for every scenario the spec calls for:

| Scenario | How |
| --- | --- |
| Network disconnect | `await agent.simulate_crash()` — closes the socket with no GOODBYE |
| High latency | `agent.reply_delay = <seconds>` (before ACK) or `agent.handler_delay = <seconds>` (before the result) |
| Duplicate packets | `agent.duplicate_next_result = True`, or call `send_envelope()` twice manually |
| Lost ACK | `agent.drop_next_ack = True`, or `agent.respond_to_commands = False` for "never responds at all" |
| Slow handler | `agent.handler_delay = <seconds>` |
| Invalid JWT | `tests/utils/failures.MALFORMED_TOKEN` |
| Expired token | `tests/utils/failures.expired_device_token(server, device_id)` (a full hour expired — safely beyond the default JWT clock-skew leeway, so it isn't borderline-valid) |

`FakeAgent.reply_delay` defaults to `0.03` seconds, not `0` — a real device
replying over WiFi/LAN always has *some* latency, and an ACK that arrives
with none at all can race the dispatcher's own `mark_dispatched()` database
write (the same race `server/tests/test_dispatcher_integration.py` documents
and works around for its own in-process fake agent). Don't set it to `0`
unless you're deliberately testing that race.

### Debugging guide

- **A test hangs instead of failing.** Almost always a `wait_for_*` call
  whose condition never becomes true — check the *actual* dispatcher/gateway
  settings the test's `server` fixture used (some test files override
  `DISPATCHER_ACK_TIMEOUT_SECONDS`/`DISPATCHER_EXECUTION_TIMEOUT_SECONDS`;
  see e.g. `tests/integration/test_command_timeout.py`) against what the
  `FakeAgent` is actually configured to do (or not do).
- **See what's happening.** Run the failing test with `-s` (or drop
  `LogCapture` in a one-off script) to see the real server's structured logs
  interleaved with `httpx`'s request logs — every REST call, every WebSocket
  event, every dispatcher sweep is logged.
- **A specific envelope's shape is wrong.** `FakeAgent.sent`/`.received` are
  plain lists of `shared.protocol.schemas.Envelope` — print or inspect them
  directly; they're recorded in order, including from the background receive
  loop.
- **Never call `agent.recv_envelope()` on a connected agent.** Once
  `connect()` succeeds, a background task is already calling `recv()` in a
  loop (to auto-handle PING/COMMAND); a second concurrent `recv()` raises
  `websockets.exceptions.ConcurrencyError`. Use `wait_for_message()` to poll
  `agent.received` instead. `recv_envelope()`/`connect_raw()` exist only for
  tests that need to drive the handshake manually (protocol-violation tests),
  before any background loop exists.
- **Flaky under the full test suite but not alone.** The load tests
  (`tests/load/`) run many concurrent real sockets/dispatch cycles; under
  heavy machine contention (e.g. the entire suite running at once) real
  asyncio scheduling can occasionally need more than a tight timeout allows.
  These use generous timeouts (30s) for exactly this reason — if you add a
  new load test, do the same rather than tightening an existing one.

### Common failures and fixes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ConcurrencyError: cannot call recv while another coroutine is already running recv` | Manual `recv_envelope()` racing the background receive loop | Use `wait_for_message()` instead |
| A "never acks" test reports `FAILED` instead of the expected path, or vice versa | `DISPATCHER_ACK_TIMEOUT_SECONDS` too tight for a *real* socket round trip (unlike the in-process fake in `server/tests/`) | Use `default_test_settings(...)`'s override kwargs to give at least ~1s of ack timeout for real-socket tests |
| An "expired token" test doesn't actually fail authentication | The token expired by too little to exceed `jwt_clock_skew_seconds` (30s default) | Use `tests.utils.failures.expired_device_token()`, which expires by a full hour |
| `RuntimeError: settings.database_url must be set for the integration harness` | A `Settings` object built without `default_test_settings()`'s required `database_url` | Always go through `default_test_settings(database_url=...)` |
| A test hangs at teardown | A `FakeAgent` never disconnected before the `server` fixture tears down | Always `await agent.disconnect()` (or `simulate_crash()`) before the test function returns |

## Design Decisions

- No mocked WebSocket transport anywhere in this framework — `FakeAgent`
  always dials a real socket, and `run_server()` always binds a real one.
- `FakeAgent` never imports `agent/app/`; it is a protocol-level black box,
  reusable regardless of how the real agent's internals evolve, and immune to
  the `app.*` namespace collision between the two packages.
- Every test gets its own fresh `ServerHarness` (its own port, its own
  temp-file SQLite database) — matching `server/tests/`'s own convention of
  a fresh `Database`/`app` per test rather than session-scoped sharing.
- `FakeAgent` supports exactly the four `system.*` command types the real
  agent's Phase 2 built-ins implement — nothing hardware-specific. A future
  GPIO/camera/scheduler command reaching an agent that doesn't implement it
  yet is exactly the "unknown command" path this framework already covers
  (`tests/integration/test_unknown_command.py`); no changes are needed here
  when hardware handlers are eventually added — the same fake, the same
  harness, the same waiters keep working.

## Future Considerations

A dedicated load-testing tool (k6, Locust) for larger-scale throughput/soak
testing beyond `tests/load/`'s modest concurrency check. Fault-injecting at
the TCP level (not just the application level `FakeAgent` already covers) —
e.g. a real proxy dropping/reordering packets — if a concrete need arises.

## Open Questions

Should `examples/verify_system.py` eventually support pointing at an
already-running server (for a staging environment smoke test) instead of
always starting its own throwaway instance?

## References

- [Testing strategy](TESTING.md)
- [Protocol](../architecture/PROTOCOL.md), [Components](../architecture/COMPONENTS.md)
- [Agent design](../agent/AGENT.md), [Commands](../agent/COMMANDS.md)
