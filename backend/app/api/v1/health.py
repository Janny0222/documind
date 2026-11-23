from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DB
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/healthz", summary="Liveness: the process is up (no dependencies checked)")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: database reachable and migrated")
async def readyz(db: DB) -> JSONResponse:
    try:
        version = (
            await db.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
    except Exception as exc:
        log.warning("readiness_failed", error_type=type(exc).__name__)
        return JSONResponse(
            {"status": "unavailable", "database": "unreachable_or_unmigrated"}, status_code=503
        )
    return JSONResponse({"status": "ok", "database": "ok", "migration": version})
