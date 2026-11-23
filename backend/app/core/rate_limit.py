"""Small in-memory fixed-window rate limiter.

Why not slowapi/Redis: the free-tier deployment runs exactly one API instance, so process
memory is a correct store and adds no infrastructure. Limits reset on restart, which is
acceptable for abuse throttling. Durable quotas (daily AI questions) are counted in Postgres
instead. If we ever scale to several instances, swap this class for a Redis-backed one.
"""

import time
from collections.abc import Awaitable, Callable
from threading import Lock

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import TooManyRequests


class FixedWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Record one hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            if len(self._hits) > 50_000:  # bound memory under abuse
                self._evict(now, window_seconds)
            if count > limit:
                return False, max(1, int(window_seconds - (now - start)))
            return True, 0

    def peek_exceeded(self, key: str, limit: int, window_seconds: int) -> int:
        """Returns retry_after if the key is already over its limit, else 0 (no hit recorded)."""
        now = time.monotonic()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= window_seconds or count < limit:
                return 0
            return max(1, int(window_seconds - (now - start)))

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def _evict(self, now: float, window_seconds: int) -> None:
        stale = [k for k, (start, _) in self._hits.items() if now - start >= window_seconds]
        for k in stale:
            del self._hits[k]


limiter = FixedWindowLimiter()


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers rewrites request.client from X-Forwarded-For behind Render.
    return request.client.host if request.client else "unknown"


def enforce(key: str, limit: int, window_seconds: int) -> None:
    if not get_settings().rate_limit_enabled:
        return
    allowed, retry_after = limiter.hit(key, limit, window_seconds)
    if not allowed:
        raise TooManyRequests(
            "Too many requests. Please wait and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(
    bucket: str, limit_getter: Callable[[], int], window_seconds: int = 60
) -> Callable[[Request], Awaitable[None]]:
    """FastAPI dependency: limit requests per client IP for one bucket."""

    async def _dependency(request: Request) -> None:
        enforce(f"{bucket}:ip:{client_ip(request)}", limit_getter(), window_seconds)

    return _dependency
