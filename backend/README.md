# DocuMind API (FastAPI)

Auth, workspaces, roles and invitations (Phase 2); document upload, parsing, chunking, a Postgres job queue and collections (Phase 4).

## Prerequisites
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.14 for you; pinned in `.python-version`)
- Docker Desktop (for Postgres 17 + pgvector)

> The Docker database listens on host port **5433** (not 5432). That way it doesn't clash with a
> natively installed Windows PostgreSQL, which usually takes 5432.

## First-time setup (PowerShell, from the repo root)
```powershell
docker compose up -d db
```
```powershell
cd backend; Copy-Item .env.example .env; uv sync
```
```powershell
uv run alembic upgrade head
```
```powershell
uv run uvicorn app.main:app --reload
```
- Swagger UI: http://localhost:8000/api/docs
- Liveness: http://localhost:8000/healthz · Readiness (DB + migration): http://localhost:8000/readyz

## Trying it in Swagger
Swagger runs on the same origin as the API, so the auth cookies work there too.
1. `GET /api/v1/auth/csrf` and copy `csrf_token`.
2. For each POST, PATCH or DELETE, add the header `X-CSRF-Token: <token>`. Swagger has no global header box, so curl or the frontend is easier for longer sessions.
3. `POST /api/v1/auth/register`. The verification link is printed in the API log (`EMAIL_BACKEND=console`).

## Tests
```powershell
uv run pytest
```
Tests use the `documind_test` database that Docker creates on first start. Each run rebuilds the schema by running all migrations down and up again. Every test starts from empty tables.

## Quality checks (the same ones CI runs)
```powershell
uv run ruff check . ; uv run ruff format --check . ; uv run mypy app ; uv run alembic check
```

## Migrations
```powershell
uv run alembic revision --autogenerate -m "describe change"
```
Always read the generated file before committing it. `alembic check` fails in CI if the models and migrations disagree.

## Layout
| Path | Responsibility |
|---|---|
| `app/core/` | config, logging, errors (problem+json), security (Argon2id, JWT), CSRF / headers / request-id middleware, rate limiter |
| `app/db/` | async engine and session (Neon-pooler aware) |
| `app/models/` | SQLAlchemy 2 typed models: all 18 tables from the Phase 1 design |
| `app/schemas/` | Pydantic v2 request and response models |
| `app/services/` | business rules and transactions (auth, workspaces, email, activity) |
| `app/api/deps.py` | `get_current_user` and `require_workspace(role)`, the authorization choke point |
| `app/api/v1/` | thin routers |
| `migrations/` | Alembic (async) |
| `app/integrations/storage.py` | Local disk (dev) or S3/R2 (prod) behind one interface; keys are server-generated |
| `app/rag/` | Ingestion: content-based validation, PDF/DOCX/TXT parsing, normalization, page-aware chunking |
| `app/workers/` | Postgres job queue (`SKIP LOCKED` + leases), in-process runner, idempotent handlers |
| `tests/` | pytest against real Postgres: auth, roles, isolation, ingestion, jobs; S3 via moto |

## How document processing works
1. **Upload** (`POST /workspaces/{id}/documents`): each file is streamed to a temp file (size-capped),
   checked by content (not by name), de-duplicated by SHA-256, and stored under a server-generated key.
   An `index_document` job is committed **in the same transaction** as the document row.
2. **Runner**: starts with the API, wakes on upload, and polls every few seconds. Jobs are claimed with
   `FOR UPDATE SKIP LOCKED` and a 5-minute lease. If the host sleeps mid-job, the lease expires and the job runs again.
3. **Index**: extract text (PDF pages / DOCX+TXT sections), strip running headers and page numbers, normalize,
   chunk with exact character offsets, then replace the document's pages and chunks in one transaction (idempotent).
4. **Failures**: bad files fail immediately with a user-facing reason (encrypted, scanned/no text, too many pages).
   Transient errors retry after 1, 5 and 30 minutes, then the document is marked failed and can be retried from the UI.
5. **Delete**: chunks, pages and collection links are removed immediately; a `purge_document` job deletes the file.

Embeddings arrive in Phase 5. Until then, chunks are stored without vectors.

A GitHub Actions cron can call `POST /api/v1/internal/jobs/drain` with the `X-Internal-Secret` header
(set `INTERNAL_API_SECRET`) to finish queued work after the free-tier host has slept.

## How answering works (RAG)
1. **Consent gate:** no document text goes to Gemini until a workspace admin allows AI processing.
   Documents indexed before that are re-queued and embedded when consent is given.
2. **Embeddings:** `gemini-embedding-001` truncated to 768 dims, L2-normalized, stored as `halfvec(768)`.
   Every chunk records its `embedding_model`. On startup, documents embedded by a different model are re-embedded,
   because vectors from different models are never compared.
3. **Retrieval:** pgvector cosine search plus Postgres full-text search, fused with Reciprocal Rank Fusion.
   Both queries filter by `workspace_id` and by the server-resolved document set **inside SQL**.
4. **Relevance floor:** if the best match is below `RETRIEVAL_MIN_SIMILARITY` and no chunk contains all of the
   question's terms, the answer is "not found" **without calling the model**. Measured for gemini-embedding-001:
   relevant pairs scored about 0.70–0.75 and unrelated ones 0.47–0.58, so the default is 0.62.
5. **Generation:** sources are wrapped in `<source id="S1">` tags as untrusted data, and the model has no tools.
   Answers stream over SSE (`meta`, `retrieval`, `token`, `citations`, `suggestions`, `done`, `error`).
6. **Citations:** only `[S#]` markers that map to a retrieved chunk survive. Each citation stores a snapshot
   (title, page, excerpt), so answers stay readable after a document is deleted.
7. **Limits and usage:** per-user daily question cap; every provider call is logged in `ai_usage_records`.
   Quota errors (429) become a friendly message and never trigger paid usage.

Tests use `AI_PROVIDER=fake` (offline and deterministic), so CI needs no API key or quota.

## Search, analytics and notifications
- **Search** (`POST /workspaces/{id}/search`): the same hybrid retrieval with no model call, so it doesn't count
  toward the daily question limit. Without AI consent (or if Gemini is unavailable) it falls back to keyword-only
  matching and says so (`mode: "keyword"`).
- **Analytics** (`GET /workspaces/{id}/analytics?days=7|30|90`, admins): question outcomes, tokens per day (zero-filled),
  document status, top askers, recent AI errors. Cost is an **estimate** from list prices, not a bill.
- **Activity** (`GET /workspaces/{id}/activity`, admins): the audit log, keyset-paginated.
- **Notifications** (`GET /notifications`, `POST /notifications/read`): document ready/failed, invitations for an
  existing account (no token in the payload; accepted via `POST /invitations/{id}/accept`), and member joined.

## Production (Phase 7)
- Deployment guide: [../docs/DEPLOY.md](../docs/DEPLOY.md). Blueprint: [../render.yaml](../render.yaml).
- `ENV=production` refuses to start unless `COOKIE_SECURE=true`, email isn't console/memory, `JWT_SECRET` isn't the
  example, and `PROXY_SHARED_SECRET` is set.
- **Proxy secret:** with `PROXY_SHARED_SECRET` set, `/api/*` requests without a matching `X-Proxy-Secret` header get
  `403 direct_access_denied`. Only the Cloudflare Pages Function adds it, so nobody can go around the proxy or forge
  `X-Forwarded-For` to dodge rate limits. `/healthz`, `/readyz` and `/api/v1/internal/*` are exempt.
- **Database URLs** can be pasted as providers show them (`postgresql://…?sslmode=require&channel_binding=require`);
  they are converted for asyncpg, and a Neon `-pooler` host turns on PgBouncer-safe settings.
- **Demo workspace** (`DEMO_ENABLED=true`): seeded on startup from `app/demo/samples/` (synthetic documents), joined as
  a viewer via `POST /api/v1/demo/join`, 10 questions per user per day inside it, members can't see each other, and
  `POST /api/v1/internal/demo/reset` (nightly cron) clears conversations and restores the samples.
