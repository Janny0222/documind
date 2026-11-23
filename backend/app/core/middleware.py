"""Pure-ASGI middlewares (no BaseHTTPMiddleware, so streaming/SSE responses are untouched).

- RequestContextMiddleware: request id, structured access log (path only, no query string).
- CSRFMiddleware: double-submit token check on unsafe methods.
- SecurityHeadersMiddleware: conservative headers for a JSON API.
"""

import json
import secrets
import time
from http.cookies import SimpleCookie

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import PROBLEM_JSON, problem
from app.core.logging import get_logger

log = get_logger("app.request")

CSRF_COOKIE = "dm_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = (
            incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else secrets.token_hex(8)
        )
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )


class CSRFMiddleware:
    """Double-submit cookie: unsafe requests must echo the dm_csrf cookie in X-CSRF-Token.

    A cross-site attacker can make the browser *send* our cookies but cannot *read* them,
    so it cannot produce the matching header. SameSite=Lax cookies + same-origin hosting are
    the first defense; this is the second.
    """

    def __init__(self, app: ASGIApp, exempt_prefixes: tuple[str, ...] = ()) -> None:
        self.app = app
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in SAFE_METHODS
            or not scope["path"].startswith("/api/")
            or scope["path"].startswith(self.exempt_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        header_token = headers.get(CSRF_HEADER, "")
        cookie_token = ""
        if raw := headers.get("cookie"):
            jar: SimpleCookie = SimpleCookie()
            try:
                jar.load(raw)
                if CSRF_COOKIE in jar:
                    cookie_token = jar[CSRF_COOKIE].value
            except Exception:
                cookie_token = ""

        if (
            not header_token
            or not cookie_token
            or not secrets.compare_digest(header_token, cookie_token)
        ):
            await _send_problem(
                send,
                403,
                "csrf_failed",
                "CSRF check failed",
                "Missing or invalid CSRF token. Call GET /api/v1/auth/csrf first.",
            )
            return
        await self.app(scope, receive, send)


class ProxySecretMiddleware:
    """In production the browser reaches the API only through the Cloudflare Pages proxy, which
    adds X-Proxy-Secret. Requests that skip the proxy (straight to *.onrender.com) are refused, so
    nobody can bypass it or forge X-Forwarded-For to dodge per-IP rate limits. Health checks and
    the secret-protected internal routes (GitHub Actions cron) are exempt."""

    def __init__(self, app: ASGIApp, secret: str, exempt_prefixes: tuple[str, ...] = ()) -> None:
        self.app = app
        self.secret = secret
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/api/")
            or scope["path"].startswith(self.exempt_prefixes)
        ):
            await self.app(scope, receive, send)
            return
        given = Headers(scope=scope).get("x-proxy-secret", "")
        if not given or not secrets.compare_digest(given, self.secret):
            await _send_problem(
                send, 403, "direct_access_denied", "Forbidden", "Use the DocuMind web app."
            )
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h.setdefault("X-Content-Type-Options", "nosniff")
                h.setdefault("X-Frame-Options", "DENY")
                h.setdefault("Referrer-Policy", "no-referrer")
                h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                if not scope["path"].startswith(("/api/docs", "/api/openapi")):
                    h.setdefault(
                        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
                    )
                    h.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            await send(message)

        await self.app(scope, receive, send_wrapper)


async def _send_problem(send: Send, status: int, code: str, title: str, detail: str) -> None:
    body = json.dumps(problem(status, code, title, detail)).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", PROBLEM_JSON.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
