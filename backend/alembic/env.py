"""Alembic environment (async, PostgreSQL)."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  # registers all models on Base.metadata
from app.db.base import Base

config = context.config

# Callers that run migrations programmatically (tests) set configure_logger=False so
# that Alembic does not replace the logging setup of the host process.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL from the Alembic config if a caller set one, otherwise BAMBUBRIDGE_DATABASE_URL.

    Only the one variable is read, so the CLI works without the other startup settings.
    """
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("BAMBUBRIDGE_DATABASE_URL")
    if not url:
        raise SystemExit("BAMBUBRIDGE_DATABASE_URL is not set")
    return url


def run_migrations_offline() -> None:
    """Emit SQL without a database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
