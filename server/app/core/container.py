"""Dependency-injector root container for explicit application composition."""

from dependency_injector import containers, providers

from app.application.events.bus import EventBus
from app.application.events.logging_subscriber import register_logging_subscriber
from app.config.settings import Settings
from app.core.database import Database
from app.core.mediamtx_jwt import build_mediamtx_jwt_signer
from app.dispatcher.dispatcher import CommandDispatcher
from app.websocket.manager import SessionManager


class ApplicationContainer(containers.DeclarativeContainer):
    """Root container holding only foundation dependencies.

    The container is instantiated by the application factory and attached to that app;
    it is never a module-level singleton. Future adapters and services must be exposed
    here as typed providers rather than constructed ad hoc in request handlers.
    """

    settings = providers.Dependency(instance_of=Settings)
    database = providers.Object(None)  # type: ignore[var-annotated]
    event_bus = providers.Singleton(EventBus)
    session_manager = providers.Singleton(SessionManager)
    mediamtx_jwt_signer = providers.Singleton(build_mediamtx_jwt_signer, settings=settings)
    dispatcher = providers.Singleton(
        CommandDispatcher,
        settings=settings,
        database=database,
        event_bus=event_bus,
        session_manager=session_manager,
    )


def build_container(settings: Settings) -> ApplicationContainer:
    """Build a new root container for one application instance."""
    database_url = settings.database_url.get_secret_value() if settings.database_url else None
    database = Database(database_url) if database_url else None
    container = ApplicationContainer(settings=settings, database=database)
    register_logging_subscriber(container.event_bus())
    return container
