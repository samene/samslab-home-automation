"""The command runtime: receive, validate, acknowledge, dispatch, execute, report.

Transport-independent — nothing here imports the WebSocket connection or the
transport-level ``MessageDispatcher``; ``CommandDispatcher.handle_command`` is
simply registered against it (see ``app/lifecycle/factory.py``). The runtime
never knows a handler's own implementation and never branches on
``command_type``; a future GPIO/camera/scheduler plugin only ever needs to
register a new ``CommandHandler``.
"""

from app.commands.builtin import (
    SystemCapabilitiesHandler,
    SystemEchoHandler,
    SystemHealthHandler,
    SystemPingHandler,
    register_builtin_handlers,
)
from app.commands.context import CommandContext, CommandServices, build_command_context
from app.commands.dispatcher import CommandDispatcher
from app.commands.events import CommandEvent, CommandEventBus
from app.commands.exceptions import (
    CommandRuntimeError,
    CommandValidationError,
    DuplicateHandlerError,
    HandlerNotFoundError,
    InvalidLifecycleTransitionError,
)
from app.commands.executor import CommandExecutor, ExecutorConfig
from app.commands.handler import DEFAULT_COMMAND_TIMEOUT_SECONDS, CommandHandler
from app.commands.lifecycle import (
    ALLOWED_TRANSITIONS,
    RESULT_STATUS_TO_LIFECYCLE_STATE,
    CommandLifecycle,
    CommandLifecycleState,
)
from app.commands.registry import CommandRegistry
from app.commands.result import (
    EXIT_CODE_CANCELLED,
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_TIMEOUT,
    CommandResult,
    CommandResultStatus,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "DEFAULT_COMMAND_TIMEOUT_SECONDS",
    "EXIT_CODE_CANCELLED",
    "EXIT_CODE_FAILURE",
    "EXIT_CODE_SUCCESS",
    "EXIT_CODE_TIMEOUT",
    "RESULT_STATUS_TO_LIFECYCLE_STATE",
    "CommandContext",
    "CommandDispatcher",
    "CommandEvent",
    "CommandEventBus",
    "CommandExecutor",
    "CommandHandler",
    "CommandLifecycle",
    "CommandLifecycleState",
    "CommandRegistry",
    "CommandResult",
    "CommandResultStatus",
    "CommandRuntimeError",
    "CommandServices",
    "CommandValidationError",
    "DuplicateHandlerError",
    "ExecutorConfig",
    "HandlerNotFoundError",
    "InvalidLifecycleTransitionError",
    "SystemCapabilitiesHandler",
    "SystemEchoHandler",
    "SystemHealthHandler",
    "SystemPingHandler",
    "build_command_context",
    "register_builtin_handlers",
]
