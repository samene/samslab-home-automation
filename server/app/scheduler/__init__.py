"""Workflow Schedules: an APScheduler-backed trigger that only ever calls
``WorkflowApplicationService.run_workflow`` — the same call "Run Now" makes.

Coordinates, never executes: this package knows nothing about Workflows,
Commands, or hardware. See ``scheduler.py``'s ``WorkflowScheduler`` and
``app.application.services.schedule_service.ScheduleApplicationService``
(where the actual "what happens when a schedule fires" business logic
lives).
"""
