# Data Flow

## Purpose

Document how control, telemetry, logs, and media move through Sam's Lab.

## Scope

Covers agent/server flows and durable recovery paths.

## Architecture

```mermaid
sequenceDiagram
  participant UI as Web UI
  participant S as Server
  participant DB as PostgreSQL
  participant A as Pi Agent
  participant Q as SQLite/spool
  UI->>S: REST action + request ID
  S->>DB: persist command QUEUED
  S->>A: COMMAND (UUID, correlation ID)
  A->>Q: durably record receipt/result
  A->>A: dispatch through driver
  A->>S: COMMAND_RESULT
  S->>DB: persist terminal state
  S-->>UI: command status
```

Telemetry, events, logs, and metrics originate at the agent; each is framed as a protocol message and retained locally until acknowledged when delivery matters. Media receives an authorized upload destination from the server, uploads over TLS to object storage, then reports metadata to the server.

### Command creation (implemented)

Creating a command only ever persists intent; the application layer, not the Command domain, is what confirms the target device exists and is enabled:

```mermaid
sequenceDiagram
  participant Client as REST client
  participant API as Command API
  participant App as CommandApplicationService
  participant DevSvc as DeviceService
  participant CmdSvc as CommandService
  participant DB as PostgreSQL
  participant Bus as EventBus
  Client->>API: POST /commands
  API->>App: create_command(request)
  App->>DevSvc: get_device(device_id)
  DevSvc->>DB: SELECT device
  App->>App: check device.enabled
  App->>CmdSvc: create_command(request)
  CmdSvc->>DB: INSERT commands, command_events
  App->>Bus: publish(CommandCreated)
  App-->>API: CommandDetailDTO
  API-->>Client: 201 (status=PENDING)
```

A command sits in `PENDING` — with a durable, queryable record and a `COMMAND_CREATED` event — until the Command Dispatcher (below) discovers and delivers it.

### The WebSocket Gateway connection lifecycle (implemented)

The agent WebSocket carries the protocol in [Protocol](PROTOCOL.md). The connection lifecycle itself — independent of whether any command is ever dispatched over it — is:

```mermaid
sequenceDiagram
  participant A as Pi Agent
  participant WS as WebSocket Gateway
  participant Auth as Auth core (decode_principal)
  participant App as DeviceApplicationService
  participant DB as PostgreSQL
  participant SM as SessionManager (in-memory)
  A->>WS: WebSocket upgrade
  WS->>A: accepted
  A->>WS: HELLO (token, agent_version)
  WS->>Auth: decode_principal(token)
  Auth-->>WS: Principal (device_id, roles)
  WS->>App: get_device(device_id)
  App->>DB: SELECT device
  App-->>WS: DeviceDTO (enabled, status)
  WS->>SM: register(session)
  WS->>App: heartbeat(device_id, status=ONLINE)
  App->>DB: UPDATE device
  WS-->>A: WELCOME (session_id, heartbeat interval/timeout)
  loop while connected
    A-->>WS: EVENT / LOG / PING / GOODBYE
    WS-->>A: MESSAGE_ACK / PONG (as applicable)
    WS->>A: PING (every heartbeat interval)
  end
  A--xWS: disconnect (GOODBYE, timeout, or transport drop)
  WS->>SM: unregister(device_id)
  WS->>App: heartbeat(device_id, status=OFFLINE)
  App->>DB: UPDATE device
```

### The Command Dispatcher: discovery through completion (implemented)

This is the sequence the very first diagram in this document sketched as the target end state — now real. The dispatcher (`server/app/dispatcher/`) never talks to a device directly; it only ever calls `CommandApplicationService` and the gateway's `SessionManager`, and reacts to `CommandAckReceived`/`CommandResultReceived` events the gateway publishes when it parses an agent's `COMMAND_ACK`/`COMMAND_RESULT`:

```mermaid
sequenceDiagram
  participant App as CommandApplicationService
  participant Worker as DispatchWorker
  participant SM as SessionManager
  participant WS as WebSocket Gateway
  participant A as Pi Agent
  participant Ack as AckManager
  participant To as TimeoutMonitor
  participant Bus as EventBus

  Worker->>App: list_pending_commands()
  App-->>Worker: [CommandDetailDTO, ...]
  Worker->>Worker: queue by priority (CRITICAL..LOW, FIFO)
  Worker->>SM: is device connected?
  SM-->>Worker: yes
  Worker->>SM: send(device_id, COMMAND envelope)
  SM->>WS: enqueue on connection
  WS-->>A: COMMAND
  Worker->>App: mark_dispatched(command_id)
  Worker->>Ack: track(item) — starts ack-timeout window

  A-->>WS: COMMAND_ACK
  WS->>Bus: publish(CommandAckReceived)
  Bus->>Ack: handle_ack(event)
  Ack->>App: mark_running(command_id)
  Ack->>To: track(item) — starts execution-timeout window

  A->>A: execute through a driver
  A-->>WS: COMMAND_RESULT
  WS->>Bus: publish(CommandResultReceived)
  Bus->>To: handle_result(event)
  To->>App: complete_command / fail_command
```

Two failure paths run alongside the happy path above, both handled without any REST/agent interaction:

- **No `COMMAND_ACK` in time** — `AckManager`'s sweep retries the send with exponential backoff (1s, 2s, 4s, 8s by default, each attempt recorded via `record_retry`) up to a configurable maximum, then calls `fail_command`.
- **No `COMMAND_RESULT` in time** — once RUNNING, `TimeoutMonitor`'s sweep calls `mark_timeout` if the execution window elapses with no result.

A device that is not connected when the worker checks is never a failure — the command is left queued and retried on the next poll. A late ack/result for a command no longer tracked (already failed, timed out, or completed) is logged and dropped, never reprocessed. See [Components](COMPONENTS.md) for file-level ownership and [Protocol](PROTOCOL.md) for the acknowledgement/retry/timeout semantics.

### The agent's own connect/heartbeat/reconnect loop (implemented, Phase 1)

The sequence above shows the server's view of one connection. This is the agent's own view of the same connection — `agent/app/lifecycle/`'s `Agent.run()`, independent of whether any command is ever dispatched over it:

```mermaid
sequenceDiagram
  participant Agent as Agent (lifecycle)
  participant SM as StateMachine
  participant CM as ConnectionManager
  participant WS as WebSocket Gateway
  participant Disp as MessageDispatcher

  Agent->>SM: transition_to(INITIALIZING)
  Agent->>Agent: plugin_manager.startup()
  Agent->>CM: connect()
  CM->>SM: transition_to(CONNECTING)
  CM->>WS: WebSocket upgrade
  CM->>WS: HELLO (token, agent_version)
  WS-->>CM: WELCOME (session_id, heartbeat interval/timeout)
  CM->>SM: transition_to(AUTHENTICATING) / transition_to(ONLINE)

  loop while connected
    CM->>WS: PING (every HEARTBEAT_INTERVAL)
    WS-->>CM: PONG
    WS-->>CM: PING / ERROR / GOODBYE (server-initiated)
    CM->>Disp: dispatch(envelope)
    Disp->>CM: send(PONG) (if PING)
  end

  WS--xCM: connection lost (drop, GOODBYE, or request_stop())
  Agent->>SM: transition_to(DISCONNECTED)
  Agent->>CM: reconnect() — exponential backoff, then connect() again
```

Every reconnection attempt after the very first goes through `reconnect()`'s backoff, whether the first attempt failed outright or an established connection was lost later — a dropped connection never hot-loops. `COMMAND` messages are received and would reach `MessageDispatcher.dispatch()`, but no handler is registered for them yet, so they are logged and ignored; wiring real command execution into this loop is future work. See [Agent design](../agent/AGENT.md) and [Components](COMPONENTS.md) for file-level ownership.

## Design Decisions

- Command status is durable on both sides until reconciliation.
- Event ordering is scoped to an agent stream and sequence number.
- Metrics use Prometheus-compatible collection, not command transport.

## Future Considerations

Introduce batching, compression, dead-letter review, and media processing queues as traffic grows.

## Open Questions

What delivery guarantee is needed for each event class?

## References

- [Protocol](PROTOCOL.md)
- [Commands](../agent/COMMANDS.md)
