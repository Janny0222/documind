"""Centralized, environment-driven configuration.

Every tunable lives here so the rest of the code never reads os.environ directly.
Values come from environment variables (or backend/.env in development).
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# libpq options that asyncpg doesn't accept as connect() keywords.
_LIBPQ_ONLY = {"channel_binding", "options", "application_name", "connect_timeout"}


def normalize_database_url(url: str) -> str:
    """Accept a provider's plain libpq URL (Neon gives
    `postgresql://...?sslmode=require&channel_binding=require`) and turn it into what
    SQLAlchemy + asyncpg expect, so it can be pasted as-is."""
    parts = urlsplit(url.strip())
    scheme = "postgresql+asyncpg" if parts.scheme in ("postgres", "postgresql") else parts.scheme
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            query.append(("ssl", value))
        elif key not in _LIBPQ_ONLY:
            query.append((key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    # env_ignore_empty: `INTERNAL_API_SECRET=` in .env means "not set" (use the default), not
    # "an empty secret" - otherwise optional features would switch on with a blank password.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "DocuMind API"
    log_level: str = "INFO"
    log_json: bool = False
    expose_docs: bool = True

    # --- Database ---
    database_url: str = "postgresql+asyncpg://documind:documind@localhost:5432/documind"
    # True when DATABASE_URL is a PgBouncer / Neon pooled endpoint (transaction pooling).
    database_pooled: bool = False
    migrations_database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Auth ---
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "documind"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # A refresh token reused within this window is treated as a benign race between tabs,
    # not as theft (the session is not revoked).
    refresh_reuse_grace_seconds: int = 10
    email_token_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60
    password_min_length: int = 10

    # --- Cookies / HTTP ---
    cookie_secure: bool = True
    cookie_domain: str | None = None
    cors_origins: list[str] = []
    # Shared with the Cloudflare Pages proxy (PROXY_SECRET there). When set, /api/* requests
    # without it are refused, so the API can't be reached around the proxy.
    proxy_shared_secret: SecretStr | None = None
    frontend_url: str = "http://localhost:5173"

    # --- Email ---
    email_backend: Literal["console", "memory", "disabled"] = "console"
    email_verification_required: bool = False

    # --- Workspaces ---
    max_owned_workspaces: int = 5
    # Shared read-only demo workspace with sample documents (seeded on startup, reset nightly).
    demo_enabled: bool = False
    invitation_ttl_days: int = 7

    # --- Rate limits (requests per window) ---
    rate_limit_enabled: bool = True
    login_ip_limit_per_minute: int = 10
    login_email_failures_per_15_min: int = 8
    auth_misc_limit_per_minute: int = 5

    # --- Internal endpoints (cron drain etc.) ---
    internal_api_secret: SecretStr | None = None

    # --- Object storage ---
    # local: files under storage_local_dir (dev/tests). s3: any S3 API - Backblaze B2 in prod.
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "var/storage"
    # Any S3-compatible service. Backblaze B2: https://s3.<region>.backblazeb2.com
    # (region is read from it); Cloudflare R2: https://<account_id>.r2.cloudflarestorage.com
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "auto"
    download_url_ttl_seconds: int = 60

    # --- Documents & processing limits (free-tier guardrails, Phase 1 §G) ---
    max_upload_mb: int = 10
    max_documents_per_workspace: int = 50
    # Ceiling on all stored uploads across every workspace, so a public deployment can't outgrow
    # the storage provider's free tier however many people sign up. 0 = no limit.
    max_total_storage_mb: int = 2048
    max_pages_per_document: int = 300
    max_chunks_per_workspace: int = 15_000
    max_files_per_upload: int = 10
    chunk_size_chars: int = 3200  # ~800 tokens at ~4 chars/token
    chunk_overlap_chars: int = 480  # ~120 tokens
    min_text_chars: int = 40  # below this a document is treated as "no extractable text"

    # --- Background jobs (Postgres queue, in-process runner) ---
    job_runner_enabled: bool = True
    job_poll_seconds: float = 5.0
    job_lease_seconds: int = 300
    job_max_attempts: int = 3

    # --- AI (Phase 5). Model names are config, never hard-coded (Phase 1 §G). ---
    # gemini = real API (needs GEMINI_API_KEY); fake = deterministic offline provider (tests/dev).
    ai_provider: Literal["gemini", "fake"] = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768  # must match the halfvec(768) column; changing it needs a migration
    embedding_batch_size: int = 50
    ai_temperature: float = 0.2
    ai_max_output_tokens: int = 1024
    ai_rewrite_followups: bool = True
    # Free-tier guardrails
    ai_daily_questions_per_user: int = 30
    ai_daily_questions_demo: int = 10  # per user, inside the shared demo workspace
    # Retrieval
    retrieval_candidates: int = 20  # per method (vector, keyword) before fusion
    retrieval_final_k: int = 6
    # Relevance floor for gemini-embedding-001@768 (cosine). Measured 2026-11-23: relevant
    # question/passage pairs scored ~0.70-0.75, unrelated ones 0.47-0.58. Below the floor (and with
    # no all-terms keyword match) we answer "not found" without a model call. Re-measure when
    # changing the embedding model - the scale is model-specific.
    retrieval_min_similarity: float = 0.62
    context_char_budget: int = 18_000
    # Cost *estimates* (USD per 1M tokens) - list prices, not billing data. 0 on the free tier.
    price_chat_input_per_m: float = 0.0
    price_chat_output_per_m: float = 0.0
    price_embedding_per_m: float = 0.0

    @field_validator("database_url", "migrations_database_url")
    @classmethod
    def _normalize_db_url(cls, v: str | None) -> str | None:
        return normalize_database_url(v) if v else v

    @model_validator(mode="after")
    def _detect_pooler(self) -> "Settings":
        # Neon's pooled endpoint has "-pooler." in the host; PgBouncer needs the asyncpg tweaks.
        if "-pooler." in urlsplit(self.database_url).netloc:
            self.database_pooled = True
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def effective_migrations_url(self) -> str:
        return self.migrations_database_url or self.database_url

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        if self.is_production:
            problems: list[str] = []
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
            if self.email_backend in ("console", "memory"):
                problems.append("EMAIL_BACKEND console/memory would leak tokens into logs")
            if "change-me" in self.jwt_secret.get_secret_value():
                problems.append("JWT_SECRET is still the example value")
            if self.proxy_shared_secret is None:
                problems.append("PROXY_SHARED_SECRET must be set (same value as the Pages proxy)")
            if problems:
                raise ValueError("; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
