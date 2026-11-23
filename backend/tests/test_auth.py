import re

import pytest

from app.core.config import get_settings
from app.services import email
from tests.conftest import PASSWORD, ApiClient, UserFactory, _new_client

AUTH = "/api/v1/auth"


def _token_from_outbox(kind: str) -> str:
    msg = email.outbox[-1]
    match = re.search(rf"/{kind}#token=([\w-]+)", msg.body)
    assert match, msg.body
    return match.group(1)


async def test_register_logs_in_and_creates_personal_workspace(make_user: UserFactory) -> None:
    client = await make_user("alice@example.com", "Alice")

    assert {"dm_access", "dm_refresh", "dm_csrf"} <= set(client.cookies.keys())
    me = await client.get("/api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    assert me.json()["email_verified"] is False

    workspaces = (await client.get("/api/v1/workspaces")).json()
    assert len(workspaces) == 1
    assert workspaces[0]["is_personal"] is True
    assert workspaces[0]["role"] == "owner"


async def test_auth_cookies_are_httponly(anon: ApiClient) -> None:
    r = await anon.post(
        f"{AUTH}/register",
        json={"email": "c@example.com", "password": PASSWORD, "display_name": "C"},
    )
    set_cookies = r.headers.get_list("set-cookie")
    access = next(c for c in set_cookies if c.startswith("dm_access="))
    refresh = next(c for c in set_cookies if c.startswith("dm_refresh="))
    csrf = next(c for c in set_cookies if c.startswith("dm_csrf="))
    assert "HttpOnly" in access and "HttpOnly" in refresh
    assert "HttpOnly" not in csrf  # the SPA must read this one
    assert "Path=/api/v1/auth" in refresh
    assert "samesite=strict" in refresh.lower()


async def test_duplicate_email_is_rejected_case_insensitively(
    make_user: UserFactory, anon: ApiClient
) -> None:
    await make_user("alice@example.com")
    r = await anon.post(
        f"{AUTH}/register",
        json={"email": "ALICE@example.com", "password": PASSWORD, "display_name": "A"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "email_taken"


async def test_weak_password_rejected_without_echoing_input(anon: ApiClient) -> None:
    r = await anon.post(
        f"{AUTH}/register",
        json={"email": "a@example.com", "password": "short", "display_name": "A"},
    )
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "short" not in r.text  # submitted values are never reflected


async def test_login_errors_do_not_reveal_which_emails_exist(
    make_user: UserFactory, anon: ApiClient
) -> None:
    await make_user("alice@example.com")
    wrong_pw = await anon.post(
        f"{AUTH}/login", json={"email": "alice@example.com", "password": "nope-nope-nope"}
    )
    no_user = await anon.post(
        f"{AUTH}/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["code"] == no_user.json()["code"] == "invalid_credentials"


async def test_login_success(make_user: UserFactory, anon: ApiClient) -> None:
    await make_user("alice@example.com")
    r = await anon.post(f"{AUTH}/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "alice@example.com"
    assert (await anon.get("/api/v1/users/me")).status_code == 200


async def test_unsafe_request_without_csrf_header_is_rejected(make_user: UserFactory) -> None:
    client = await make_user()
    r = await client.post(
        "/api/v1/workspaces", json={"name": "X"}, headers={"X-CSRF-Token": "wrong-token-value"}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"

    async with _new_client() as bare:  # no CSRF cookie at all
        r = await bare.post(f"{AUTH}/login", json={"email": "a@example.com", "password": PASSWORD})
        assert r.status_code == 403


async def test_protected_route_requires_auth(anon: ApiClient) -> None:
    r = await anon.get("/api/v1/users/me")
    assert r.status_code == 401
    assert r.json()["code"] == "not_authenticated"


async def test_refresh_rotates_token(make_user: UserFactory) -> None:
    client = await make_user()
    old = client.cookies.get("dm_refresh", path="/api/v1/auth")
    r = await client.post(f"{AUTH}/refresh")
    assert r.status_code == 200
    assert client.cookies.get("dm_refresh", path="/api/v1/auth") != old
    assert (await client.get("/api/v1/users/me")).status_code == 200


async def test_refresh_token_reuse_revokes_session(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    victim = await make_user()
    stolen = victim.cookies.get("dm_refresh", path="/api/v1/auth")
    assert (await victim.post(f"{AUTH}/refresh")).status_code == 200  # legit rotation

    async with _new_client() as attacker:
        await attacker.get(f"{AUTH}/csrf")
        attacker.cookies.set("dm_refresh", stolen, path="/api/v1/auth")
        r = await attacker.post(f"{AUTH}/refresh")
        assert r.status_code == 401
        assert r.json()["code"] == "session_expired"

    # The whole session is revoked: the victim's current access token stops working too.
    assert (await victim.get("/api/v1/users/me")).status_code == 401
    assert (await victim.post(f"{AUTH}/refresh")).status_code == 401


async def test_concurrent_refresh_within_grace_is_not_treated_as_theft(
    make_user: UserFactory,
) -> None:
    client = await make_user()
    old = client.cookies.get("dm_refresh", path="/api/v1/auth")
    assert (await client.post(f"{AUTH}/refresh")).status_code == 200

    async with _new_client() as other_tab:
        await other_tab.get(f"{AUTH}/csrf")
        other_tab.cookies.set("dm_refresh", old, path="/api/v1/auth")
        r = await other_tab.post(f"{AUTH}/refresh")
        assert r.status_code == 401
        assert r.json()["code"] == "refresh_race"

    assert (await client.get("/api/v1/users/me")).status_code == 200  # still logged in


async def test_logout_revokes_session(make_user: UserFactory) -> None:
    client = await make_user()
    access = client.cookies.get("dm_access", path="/api")
    assert (await client.post(f"{AUTH}/logout")).status_code == 204
    assert (await client.get("/api/v1/users/me")).status_code == 401

    # Even a copy of the old access token is dead (session-backed JWTs).
    async with _new_client() as copy:
        copy.cookies.set("dm_access", access, path="/api")
        assert (await copy.get("/api/v1/users/me")).status_code == 401


async def test_password_reset_flow(make_user: UserFactory, anon: ApiClient) -> None:
    old_session = await make_user("alice@example.com")

    r = await anon.post(f"{AUTH}/forgot-password", json={"email": "alice@example.com"})
    assert r.status_code == 202
    token = _token_from_outbox("reset-password")

    new_pw = "a-brand-new-passphrase"
    assert (
        await anon.post(f"{AUTH}/reset-password", json={"token": token, "new_password": new_pw})
    ).status_code == 200
    # single use
    assert (
        await anon.post(f"{AUTH}/reset-password", json={"token": token, "new_password": new_pw})
    ).status_code == 401
    # existing sessions were signed out
    assert (await old_session.get("/api/v1/users/me")).status_code == 401

    assert (
        await anon.post(f"{AUTH}/login", json={"email": "alice@example.com", "password": PASSWORD})
    ).status_code == 401
    assert (
        await anon.post(f"{AUTH}/login", json={"email": "alice@example.com", "password": new_pw})
    ).status_code == 200


async def test_forgot_password_for_unknown_email_looks_identical(anon: ApiClient) -> None:
    r = await anon.post(f"{AUTH}/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == 202
    assert email.outbox == []


async def test_email_verification(make_user: UserFactory) -> None:
    client = await make_user("alice@example.com")
    token = _token_from_outbox("verify-email")
    assert (await client.post(f"{AUTH}/verify-email", json={"token": token})).status_code == 200
    assert (await client.get("/api/v1/users/me")).json()["email_verified"] is True


async def test_change_password_keeps_current_session_only(
    make_user: UserFactory, anon: ApiClient
) -> None:
    client = await make_user("alice@example.com")
    r = await anon.post(f"{AUTH}/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 200  # `anon` is now a second session

    r = await client.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "another-long-passphrase"},
    )
    assert r.status_code == 204
    assert (await client.get("/api/v1/users/me")).status_code == 200
    assert (await anon.get("/api/v1/users/me")).status_code == 401


async def test_repeated_login_failures_lock_the_email(
    make_user: UserFactory, anon: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "login_email_failures_per_15_min", 3)
    await make_user("alice@example.com")
    for _ in range(3):
        r = await anon.post(
            f"{AUTH}/login", json={"email": "alice@example.com", "password": "wrong-password!"}
        )
        assert r.status_code == 401
    r = await anon.post(f"{AUTH}/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 429  # even the right password is refused during lockout
    assert "retry-after" in r.headers


async def test_ip_rate_limit_on_register(anon: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "auth_misc_limit_per_minute", 2)
    codes = []
    for i in range(3):
        r = await anon.post(
            f"{AUTH}/register",
            json={"email": f"u{i}@example.com", "password": PASSWORD, "display_name": "U"},
        )
        codes.append(r.status_code)
    assert codes == [201, 201, 429]
