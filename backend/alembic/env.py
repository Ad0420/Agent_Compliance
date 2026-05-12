"""Alembic environment configuration.

Reads DATABASE_URL from environment (or .env), connects with a sync
driver, and runs migrations against the models defined in app.models.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure the backend package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401 – side-effect: registers tables
    Organization,
    APIKey,
    Agent,
    ChainState,
    ActionRecord,
    Checkpoint,
    Policy,
    PolicyViolation,
    Approval,
    IdempotencyRecord,
    WebhookSubscription,
    OrgMembership,
    ProcessedWebhookEvent,
    ComplianceReviewRecord,
)

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_sync_url() -> str:
    """Return a *synchronous* database URL for Alembic.

    The app uses async drivers (aiosqlite / asyncpg) but Alembic runs
    synchronous migrations.  This helper swaps the async driver for a
    sync one.
    """
    url = os.getenv("DATABASE_URL", "sqlite:///./vera.db")
    # Strip async driver prefixes
    url = url.replace("sqlite+aiosqlite", "sqlite")
    url = url.replace("postgresql+asyncpg", "postgresql")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # needed for SQLite ALTER TABLE
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB)."""
    # Override the ini-file URL with our resolved one
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_sync_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # needed for SQLite ALTER TABLE
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
