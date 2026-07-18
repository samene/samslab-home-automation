# Workflows

## Purpose

Describe how a Workflow — a named, ordered sequence of Tasks — is defined, persisted, and executed entirely on top of the existing Command Framework, without modifying it.

## Scope

Defining, listing, editing, and running Workflows composed of Command Tasks and Sleep Tasks, serially or in Parallel Groups, is implemented. Scheduling (cron-like triggers), a separate "Job" abstraction, and any task type that touches hardware directly are explicitly **not** part of this feature — see Design Decisions.

## Architecture

A Workflow is the top-level executable unit; there is no Job on top of it. Its step tree is stored flat — one `workflow_steps` row per node, linked by a self-referential `parent_step_id` — rather than through a navigable ORM relationship (see [Database](DATABASE.md)); the application layer reassembles the nested tree in plain Python from one flat, ordered query each time it's needed. A `GROUP` step's `group_mode` (`SERIAL`/`PARALLEL`) governs how its own children execute; the top-level list is implicitly serial, which is what "ordered list of Tasks" means. Nesting is arbitrarily deep at the schema level (a `GROUP` can contain another `GROUP`), even though the v1 editor UI only ever builds one level of Parallel Group — this is the literal meaning of "support nested groups for future expansion."

### Execution

`WorkflowApplicationService` (`server/app/application/services/workflow_service.py`) is the one executable orchestrator — there is no separate engine/Job class. It's built the same way `CameraApplicationService` is (only `database`/`event_bus` + config, no domain service bound to a request-scoped session), because it has to wait on a process it doesn't control: a Command Task step creates a normal `Command` row via `CommandApplicationService.create_command` — exactly like the Dashboard's pump buttons or `camera.stream.start` already do — and polls for it to reach a terminal state (`_wait_for_terminal`, mirroring Camera's helper of the same name) while the already-running `CommandDispatcher` delivers it to the agent completely unaware a Workflow exists.

`run_workflow` goes one step further than Camera ever needs to: it *detaches* the wait from the HTTP request entirely, since a workflow can run far longer than one request should ever block for.

```
POST /workflows/{id}/run
  → create a workflow_run row (status=RUNNING)
  → asyncio.create_task(_execute_run(...)), tracked by WorkflowRunRegistry
  → return immediately with the run RUNNING

_execute_run walks the top-level step list serially:
  COMMAND step  → create a command, wait for it to reach COMPLETED (or raise on FAILED/TIMEOUT)
  SLEEP step    → asyncio.sleep(seconds) — no command created, nothing server-side beyond the delay
  GROUP step    → SERIAL:   recurse into the same serial walk over its children
                  PARALLEL: asyncio.gather every child's own _execute_step;
                            gather's fail-fast propagation is exactly
                            "wait until ALL complete successfully, only
                            then continue" — one failing child aborts the
                            whole group (and, propagating further, the run)
```

Every step's own `workflow_step_runs` row is created when it starts and finished (`COMPLETED`/`FAILED`/`CANCELLED`) when it ends, so a live status view can show exactly which step is currently running, which have finished, and — for a `GROUP` — how many of its children are done. A step that hasn't started yet in an in-progress run has no row at all; the application layer's mapper synthesizes a `PENDING` placeholder for it by walking the step-definition tree and pairing each node with its (possibly absent) `WorkflowStepRun`.

### Parallel cancellation

When one Parallel Group child fails, `asyncio.gather` cancels its still-running siblings. Each sibling's own step-execution code catches that `CancelledError`, best-effort calls the existing `CommandApplicationService.cancel_command` on whatever command it had in flight, and writes `CANCELLED` (not left stuck at `RUNNING`) to its own `workflow_step_runs` row before re-raising. The cancel call is genuinely best-effort — if it fails (the command already finished, the device is unreachable, whatever), a warning is logged and the workflow's own failure handling proceeds regardless; a workflow run's outcome is never blocked on successfully cancelling a stray command.

### Startup reconciliation

An `asyncio.Task` driving a run does not survive a process crash or restart, even though its `workflow_runs` row (`status=RUNNING`) does. `WorkflowService.reconcile_interrupted_runs()` sweeps every such orphaned row at application startup (`app/main.py`'s lifespan, before the dispatcher starts) and marks it `FAILED` with `"interrupted by server restart"` — mirroring `CommandService.expire_old_commands`'s existing pattern of an explicit reconciliation sweep against orphaned "in progress" state. Symmetrically, `WorkflowRunRegistry` (modeled directly on `app/websocket/manager.py`'s `SessionManager`) tracks every in-flight run's task and is drained (`wait_closed()`, bounded by `WORKFLOW_RUN_SHUTDOWN_WAIT_SECONDS`) during a graceful shutdown, so a run isn't abandoned mid-transaction the moment the process is asked to stop.

### REST surface

`GET/POST /workflows`, `PUT/DELETE /workflows/{id}`, `POST /workflows/{id}/run` — five routes, nothing more. Two things the UI needs are deliberately *not* separate endpoints:

- **Duplicate** is frontend-only: fetch a workflow's full detail, then `POST /workflows` again with the same steps and a modified name.
- **Live execution status** and the **Dashboard's "last 3 executions"** both come from data already on `GET /workflows`/`GET /workflows/{id}`. The list DTO carries denormalized `last_run_at`/`last_run_status`/`last_run_duration_ms`/`run_count` per workflow (the Dashboard sorts the already-fetched list client-side and takes the top 3 — this assumes the workflow count stays small enough that `GET /workflows` remains unpaginated in practice, a known, accepted scaling assumption). The detail DTO embeds a `latest_run` (with a recursive `step_runs` tree mirroring the step tree) that the frontend polls on a short interval only while it's `RUNNING`.

There is no `GET /workflows/{id}/runs` history browser — only the latest run is ever surfaced. This is an explicit, named deferral, not an oversight.

## Design Decisions

- **The Workflow is the only executable unit; there is no Job abstraction.** `workflow_runs`/`workflow_step_runs` are the Workflow domain's own execution history — the same shape as `command_results`/`command_events` sitting alongside `commands` — not a competing, workflow-agnostic scheduler/executor concept.
- **The Command Framework is never modified.** A Command Task creates an ordinary `Command` row through the same `CommandApplicationService.create_command`/`get_command` calls any other caller uses; the dispatcher, the agent's command handlers, and the command state machine have no notion that a Workflow exists. `correlation_id` is set to the `workflow_run_id` on every command a workflow step creates — a free, already-existing, already-indexed field — so an operator can trace "which commands did this run produce" without any new filter on `CommandService.list_commands`.
- **No hardware access outside a Command Task.** Sleep is the only non-command task; it is a pure `asyncio.sleep` inside the engine, nothing else. Any future task type must plug into the same `_execute_step` branch structure without redesigning the engine.
- **`_require_primary_device_id` is duplicated from `CameraApplicationService`, not shared.** Both currently target the same MVP "first enabled-or-not device" simplification (`DeviceApplicationService.list_devices(limit=1)`). This ~10-line private method is intentionally copied rather than extracted into a shared helper, to keep this feature's changes isolated from an already-shipped file; a future pass can unify them once a real multi-device targeting story exists for either feature. A `device_id` field on `workflow_steps` (to target a specific device) is deferred, not silently assumed away.
- **Nested groups deeper than one level are a schema capability, not a v1 UI capability.** The editor deliberately only exposes building one level of Parallel Group, matching "keep the editor simple" and the spec's own flow example (`Command → Sleep → Parallel → Command`).

## Future Considerations

Scheduling (time- or event-triggered runs), additional task types (e.g. a conditional/branching step), a `device_id` per Command Task step, and a full run-history browser beyond "the latest run" are all deferred.

## Open Questions

Should a Command Task ever be allowed to target a specific device rather than always the implicit primary one? Should concurrent runs of the *same* workflow be prevented, or is allowing them (today's behavior — each "Run Now" simply starts an independent run) the right long-term default?

## References

- [Database](DATABASE.md)
- [Components](COMPONENTS.md)
- [API](API.md)
