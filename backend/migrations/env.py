"""Alembic environment (async engine, URL from app settings)."""

import asyncio
from logging.config import fileConfig

import pgvector.sqlalchemy  # noqa: F401 - registers HALFVEC for autogenerate rendering
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure(url=get_settings().effective_migrations_url)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # Direct (non-pooled) connection: DDL and advisory locks don't belong on PgBouncer.
    engine = create_async_engine(get_settings().effective_migrations_url)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
