"""Phase 7 (deployment): shared read-only demo workspace, nightly reset, paste-as-is Neon URLs,
and the proxy secret that keeps the API behind Cloudflare Pages."""

import httpx
import pytest
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.config import Settings, get_settings, normalize_database_url
from app.core.middleware import ProxySecretMiddleware
from app.db.session import get_sessionmaker
from app.services.demo_service import DEMO_OWNER_EMAIL, seed_demo
from app.workers.runner import drain
from tests.conftest import PASSWORD, UserFactory
from tests.test_rag import ask, event

SECRET = "internal-test-secret"


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "demo_enabled", True)
    monkeypatch.setattr(s, "internal_api_secret", SecretStr(SECRET))


async def seed() -> str:
    async with get_sessionmaker()() as db:
        ws_id, _ = await seed_demo(db)
    await drain()
    return str(ws_id)


# ------------------------------------------------------------------ database URL


def test_neon_url_is_accepted_as_pasted() -> None:
    raw = "postgresql://u:p@ep-cool-1234.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert normalize_database_url(raw) == (
        "postgresql+asyncpg://u:p@ep-cool-1234.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
    )
    assert normalize_database_url("postgres://u:p@h/db").startswith("postgresql+asyncpg://")
    # Already-correct URLs pass through untouched.
    ok = "postgresql+asyncpg://documind:documind@localhost:5433/documind"
    assert normalize_database_url(ok) == ok


def test_neon_pooler_host_turns_on_pooled_mode() -> None:
    s = Settings(
        jwt_secret=SecretStr("x" * 40),
        database_url="postgresql://u:p@ep-cool-1234-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require",
        database_pooled=False,
    )
    assert s.database_pooled is True


# ------------------------------------------------------------------ demo workspace


async def test_demo_is_unavailable_until_seeded(make_user: UserFactory) -> None:
    alice = await make_user()
    assert (await alice.get("/api/v1/demo")).json() == {
        "available": False,
        "joined": False,
        "workspace_id": None,
    }
    r = await alice.post("/api/v1/demo/join")
    assert r.status_code == 404 and r.json()["code"] == "demo_unavailable"


async def test_seed_is_idempotent() -> None:
    first = await seed()
    async with get_sessionmaker()() as db:
        again, queued = await seed_demo(db)
    assert str(again) == first and queued == 0


async def test_user_joins_as_read_only_viewer_and_can_ask(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = await seed()
    alice = await make_user()
    r = await alice.post("/api/v1/demo/join")
    assert r.status_code == 200 and r.json()["workspace_id"] == ws
    assert (await alice.post("/api/v1/demo/join")).status_code == 200  # idempotent
    assert (await alice.get("/api/v1/demo")).json()["joined"] is True

    listed = {w["id"]: w for w in (await alice.get("/api/v1/workspaces")).json()}
    assert listed[ws]["role"] == "viewer" and listed[ws]["is_demo"] is True

    docs = (await alice.get(f"/api/v1/workspaces/{ws}/documents")).json()
    assert docs["total"] == 3
    assert {d["status"] for d in docs["items"]} == {"ready"}
    assert not any(d["can_edit"] for d in docs["items"])

    # Read-only: no uploads, no invitations.
    up = await alice.post(
        f"/api/v1/workspaces/{ws}/documents", files=[("files", ("x.txt", b"hello", "text/plain"))]
    )
    assert up.status_code == 403
    inv = await alice.post(f"/api/v1/workspaces/{ws}/invitations", json={"role": "viewer"})
    assert inv.status_code == 403

    # Asking works, against the sample documents, under the smaller demo quota.
    monkeypatch.setattr(get_settings(), "ai_daily_questions_demo", 1)
    status = (await alice.get(f"/api/v1/workspaces/{ws}/ai/status")).json()
    assert status["daily_limit"] == 1 and status["questions_left_today"] == 1
    conv, events = await ask(alice, ws, "How many days written notice do employees give?")
    assert event(events, "citations")
    again = await alice.post(
        f"/api/v1/workspaces/{ws}/conversations/{conv}/messages", json={"content": "And managers?"}
    )
    assert again.status_code == 429
    assert "demo workspace" in again.json()["detail"]


async def test_demo_conversations_are_private(make_user: UserFactory) -> None:
    ws = await seed()
    alice = await make_user()
    bob = await make_user("bob@example.com", "Bob")
    for c in (alice, bob):
        await c.post("/api/v1/demo/join")
    await ask(alice, ws, "What is the late payment fee?")
    assert (await bob.get(f"/api/v1/workspaces/{ws}/conversations")).json() == []
    # Visitors can't see each other in the member list either.
    members = (await bob.get(f"/api/v1/workspaces/{ws}/members")).json()
    assert [m["email"] for m in members] == ["bob@example.com"]


async def test_demo_owner_cannot_sign_in(anon: object) -> None:
    await seed()
    r = await anon.post(  # type: ignore[attr-defined]
        "/api/v1/auth/login", json={"email": DEMO_OWNER_EMAIL, "password": PASSWORD}
    )
    # .invalid fails email validation (422); even past that, the account is inactive (401).
    assert r.status_code in (401, 422)


async def test_nightly_reset_clears_conversations_and_keeps_samples(
    make_user: UserFactory, demo_on: None
) -> None:
    ws = await seed()
    alice = await make_user()
    await alice.post("/api/v1/demo/join")
    await ask(alice, ws, "What is the late payment fee?")

    assert (await alice.post("/api/v1/internal/demo/reset")).status_code == 401
    r = await alice.post("/api/v1/internal/demo/reset", headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert r.json() == {"conversations_deleted": 1, "documents_queued": 0}
    assert (await alice.get(f"/api/v1/workspaces/{ws}/conversations")).json() == []
    assert (await alice.get(f"/api/v1/workspaces/{ws}/documents")).json()["total"] == 3


# ------------------------------------------------------------------ proxy secret


def _proxied_app() -> httpx.AsyncClient:
    async def ok(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    inner = Starlette(
        routes=[
            Route("/api/v1/users/me", ok),
            Route("/api/v1/internal/jobs/drain", ok, methods=["POST"]),
            Route("/healthz", ok),
        ]
    )
    app = ProxySecretMiddleware(inner, secret="s3cret", exempt_prefixes=("/api/v1/internal/",))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def test_api_refuses_requests_that_skip_the_pages_proxy() -> None:
    async with _proxied_app() as c:
        direct = await c.get("/api/v1/users/me", headers={"X-Forwarded-For": "1.2.3.4"})
        assert direct.status_code == 403 and direct.json()["code"] == "direct_access_denied"
        assert (
            await c.get("/api/v1/users/me", headers={"X-Proxy-Secret": "wrong"})
        ).status_code == 403
        assert (
            await c.get("/api/v1/users/me", headers={"X-Proxy-Secret": "s3cret"})
        ).status_code == 200
        # Platform health checks and the cron's secret-protected routes don't go through Pages.
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.post("/api/v1/internal/jobs/drain")).status_code == 200


def test_production_requires_the_proxy_secret() -> None:
    with pytest.raises(ValueError, match="PROXY_SHARED_SECRET"):
        Settings(
            env="production",
            jwt_secret=SecretStr("x" * 40),
            cookie_secure=True,
            email_backend="disabled",
        )
