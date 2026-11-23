"""Test harness.

Tests run against a real Postgres + pgvector (docker compose `db`, database documind_test),
because tenant isolation, partial unique indexes and FK cascades are database behavior
that SQLite or mocks would not prove. The schema is built with the real Alembic
migrations (downgrade to base, then upgrade to head), so migrations are tested too.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

# Configure the app for tests BEFORE importing it.
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://documind:documind@localhost:5433/documind_test"
)
os.environ["MIGRATIONS_DATABASE_URL"] = os.environ["DATABASE_URL"]
os.environ["DATABASE_POOLED"] = "false"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256-signing"
os.environ["COOKIE_SECURE"] = "false"
os.environ["EMAIL_BACKEND"] = "memory"
os.environ["EMAIL_VERIFICATION_REQUIRED"] = "false"
os.environ["CORS_ORIGINS"] = "[]"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_DIR"] = str(
    Path(__file__).resolve().parent.parent / "var" / "test-storage"
)
# Offline, deterministic AI: no API key, no network, no quota in tests or CI.
os.environ["AI_PROVIDER"] = "fake"
# Tests run jobs explicitly with `await drain()` so every step is deterministic.
os.environ["JOB_RUNNER_ENABLED"] = "false"
# Generous limits so ordinary tests never trip them; rate-limit tests lower them explicitly.
os.environ["AUTH_MISC_LIMIT_PER_MINUTE"] = "1000"
os.environ["LOGIN_IP_LIMIT_PER_MINUTE"] = "1000"

import httpx
import pytest
from sqlalchemy import text

from app.core.rate_limit import limiter
from app.db.session import get_engine
from app.main import app
from app.models import Base
from app.services import email

BACKEND_DIR = Path(__file__).resolve().parent.parent
PASSWORD = "correct-horse-battery"


def _alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, check=True, env=os.environ.copy()
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    limiter.clear()
    email.outbox.clear()


class ApiClient(httpx.AsyncClient):
    """httpx client that behaves like the frontend: keeps cookies, sends the CSRF header."""

    async def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and (
            token := self.cookies.get("dm_csrf")
        ):
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", token)
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)


def _new_client() -> ApiClient:
    return ApiClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def anon() -> AsyncIterator[ApiClient]:
    async with _new_client() as client:
        await client.get("/api/v1/auth/csrf")
        yield client


UserFactory = Callable[..., Awaitable[ApiClient]]


@pytest.fixture
async def make_user() -> AsyncIterator[UserFactory]:
    """Registers a user and returns a logged-in client. Clients are closed after the test."""
    clients: list[ApiClient] = []

    async def _make(email: str = "alice@example.com", name: str = "Alice") -> ApiClient:
        client = _new_client()
        clients.append(client)
        await client.get("/api/v1/auth/csrf")
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "display_name": name},
        )
        assert r.status_code == 201, r.text
        return client

    yield _make
    for c in clients:
        await c.aclose()


async def personal_workspace_id(client: ApiClient) -> str:
    r = await client.get("/api/v1/workspaces")
    assert r.status_code == 200, r.text
    return next(w["id"] for w in r.json() if w["is_personal"])


async def user_id(client: ApiClient) -> str:
    r = await client.get("/api/v1/users/me")
    return str(r.json()["id"])
