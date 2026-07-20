"""The Notification Framework: Workflow Engine → Notification Event → Notification Service → Provider.

V1 implements exactly one provider (Telegram) and exactly two events
(``WorkflowCompleted``/``WorkflowFailed``, see ``events.py``). The Workflow
Engine (``app.application.services.workflow_service.WorkflowApplicationService``)
only ever imports ``app.notifications.events`` and publishes on the shared
``EventBus`` — it never imports anything else here, and never knows Telegram
(or any future provider) exists. See ``docs/architecture`` for the full
design; this package is intentionally flat and self-contained rather than
split across ``domains/``/``application/`` the way a full business domain is,
since it has no CRUD surface of its own beyond a small delivery-history log.
"""

from __future__ import annotations
