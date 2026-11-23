"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    auth,
    chat,
    demo,
    documents,
    health,
    insights,
    internal,
    users,
    workspaces,
)
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    CSRFMiddleware,
    ProxySecretMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.services.demo_service import seed_demo
from app.workers.maintenance import requeue_stale_embeddings
from app.workers.runner import start_runner, stop_runner

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    get_engine()
    log.info("startup", env=s.env, email_backend=s.email_backend, storage=s.storage_backend)
    # Re-embed documents whose vectors came from a different embedding model, then start the
    # runner (it also picks up jobs whose lease expired while the host slept).
    try:
        await requeue_stale_embeddings()
    except Exception:  # never block startup on maintenance
        log.exception("stale_embedding_check_failed")
    if s.demo_enabled:
        try:
            async with get_sessionmaker()() as db:
                await seed_demo(db)
        except Exception:
            log.exception("demo_seed_failed")
    start_runner()
    yield
    await stop_runner()
    await dispose_engine()
    log.info("shutdown")


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)

    app = FastAPI(
        title=s.app_name,
        version="0.1.0",
        description="DocuMind API - AI-powered document intelligence.",
        lifespan=lifespan,
        docs_url="/api/docs" if s.expose_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if s.expose_docs else None,
    )
    register_exception_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    for module in (auth, users, workspaces, documents, chat, insights, demo, internal):
        v1.include_router(module.router)
    app.include_router(v1)
    app.include_router(health.router)  # /healthz, /readyz at the root for the platform

    # add_middleware wraps, so the last added runs first (outermost).
    app.add_middleware(CSRFMiddleware, exempt_prefixes=("/api/v1/internal/",))
    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        )
    if s.proxy_shared_secret:
        app.add_middleware(
            ProxySecretMiddleware,
            secret=s.proxy_shared_secret.get_secret_value(),
            exempt_prefixes=("/api/v1/internal/",),
        )
    app.add_middleware(SecurityHeadersMiddleware, hsts=s.is_production)
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
