"""Auth cookie policy in one place.

dm_access   HttpOnly, SameSite=Lax,    Path=/api          short-lived JWT
dm_refresh  HttpOnly, SameSite=Strict, Path=/api/v1/auth  only sent to auth endpoints
dm_csrf     readable by JS, SameSite=Lax, Path=/          echoed in X-CSRF-Token

JavaScript can't read the auth cookies, so an XSS bug can't steal them (no tokens in
localStorage). The frontend and API share one origin (Vite proxy / Pages Function), so
these are first-party cookies and aren't hit by third-party cookie blocking.
"""

import secrets

from fastapi import Request, Response

from app.core.config import get_settings
from app.core.middleware import CSRF_COOKIE
from app.services.auth_service import IssuedTokens

ACCESS_COOKIE = "dm_access"
REFRESH_COOKIE = "dm_refresh"
ACCESS_PATH = "/api"
REFRESH_PATH = "/api/v1/auth"


def set_auth_cookies(response: Response, tokens: IssuedTokens) -> None:
    s = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=s.access_token_ttl_minutes * 60,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path=ACCESS_PATH,
        domain=s.cookie_domain,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=s.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path=REFRESH_PATH,
        domain=s.cookie_domain,
    )
    set_csrf_cookie(response)  # rotate on login/refresh (prevents CSRF token fixation)


def clear_auth_cookies(response: Response) -> None:
    s = get_settings()
    for name, path in ((ACCESS_COOKIE, ACCESS_PATH), (REFRESH_COOKIE, REFRESH_PATH)):
        response.delete_cookie(
            name, path=path, domain=s.cookie_domain, secure=s.cookie_secure, httponly=True
        )


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    s = get_settings()
    token = token or secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=s.refresh_token_ttl_days * 86400,
        httponly=False,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
        domain=s.cookie_domain,
    )
    return token


def existing_csrf(request: Request) -> str | None:
    token = request.cookies.get(CSRF_COOKIE)
    return token if token and 20 <= len(token) <= 100 else None
