"""Alembic environment that imports metadata without creating application services."""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.database import Base
from app.domains.auth import models as auth_models  # noqa: F401
from app.domains.commands import models as commands_models  # noqa: F401
from app.domains.devices import models as devices_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

# alembic.ini's sqlalchemy.url is a local-dev placeholder; a real DATABASE_URL
# in the environment (as every deployment — container or otherwise — already
# provides for the app itself) always overrides it. psycopg3's dialect
# accepts the same "postgresql+psycopg://" URL for both this sync engine and
# the application's own async one, so no scheme rewriting is needed here.
if database_url := os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Generate SQL without a live database connection."""
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using Alembic's sync engine as required by its runtime."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
