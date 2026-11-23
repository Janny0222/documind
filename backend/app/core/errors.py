"""One error shape for the whole API: RFC 9457 problem+json with a stable `code`.

Services raise AppError subclasses; the handlers here turn them (and framework errors)
into consistent responses. Unexpected exceptions return a generic 500 without internals.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra or {}
        self.headers = headers
        super().__init__(self.detail)


class Unauthorized(AppError):
    status_code, code, title = 401, "unauthorized", "Authentication required"


class Forbidden(AppError):
    status_code, code, title = 403, "forbidden", "You do not have permission to do this"


class NotFound(AppError):
    status_code, code, title = 404, "not_found", "Resource not found"


class Conflict(AppError):
    status_code, code, title = 409, "conflict", "Conflict"


class TooManyRequests(AppError):
    status_code, code, title = 429, "rate_limited", "Too many requests"


class ValidationFailed(AppError):
    status_code, code, title = 422, "validation_error", "Validation failed"


def problem(
    status: int, code: str, title: str, detail: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"https://documind.dev/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
    }
    if extra:
        body.update(extra)
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            problem(exc.status_code, exc.code, exc.title, exc.detail, exc.extra),
            status_code=exc.status_code,
            media_type=PROBLEM_JSON,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]  # deliberately omits the submitted `input` (could be a password)
        return JSONResponse(
            problem(
                422, "validation_error", "Validation failed", "Invalid request", {"errors": errors}
            ),
            status_code=422,
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            problem(exc.status_code, code, str(exc.detail), str(exc.detail)),
            status_code=exc.status_code,
            media_type=PROBLEM_JSON,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            problem(500, "internal_error", "Internal server error", "Something went wrong"),
            status_code=500,
            media_type=PROBLEM_JSON,
        )
