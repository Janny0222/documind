"""Async SQLAlchemy engine + session factory.

One engine per process. With Neon's pooled endpoint (PgBouncer, transaction mode) asyncpg's
prepared-statement cache breaks, because consecutive statements can land on different server
connections; DATABASE_POOLED=true disables the cache and uses unique statement names.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args(pooled: bool) -> dict[str, Any]:
    if not pooled:
        return {}
    return {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
    }


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,  # Neon scales to zero; detect dropped connections
            pool_recycle=300,
            connect_args=_connect_args(s.database_pooled),
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Services commit explicitly; anything uncommitted is rolled back."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
