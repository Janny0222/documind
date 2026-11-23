"""Internal endpoints for automation (not for browsers): a GitHub Actions cron calls the drain
endpoint hourly so queued work finishes even if the free-tier host slept. Protected by a shared
secret header instead of cookies; CSRF middleware exempts /api/v1/internal/."""

from typing import Annotated

from fastapi import APIRouter, Header

from app.api.deps import DB
from app.core.config import get_settings
from app.core.errors import NotFound, Unauthorized
from app.core.security import constant_time_equals
from app.services import demo_service
from app.workers.runner import drain, nudge_runner

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


def _check_secret(given: str | None) -> None:
    secret = get_settings().internal_api_secret
    if secret is None:
        raise NotFound()  # feature disabled: behave as if the route doesn't exist
    if not given or not constant_time_equals(given, secret.get_secret_value()):
        raise Unauthorized("Invalid internal secret", code="invalid_internal_secret")


@router.post("/jobs/drain")
async def drain_jobs(x_internal_secret: Annotated[str | None, Header()] = None) -> dict[str, int]:
    _check_secret(x_internal_secret)
    return {"jobs_run": await drain(max_jobs=100)}


@router.post("/demo/reset")
async def reset_demo(
    db: DB, x_internal_secret: Annotated[str | None, Header()] = None
) -> dict[str, int]:
    """Nightly cron: clear demo conversations and restore the sample documents."""
    _check_secret(x_internal_secret)
    if not get_settings().demo_enabled:
        raise NotFound()
    result = await demo_service.reset_demo(db)
    nudge_runner()
    return result
