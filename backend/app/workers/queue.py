"""Postgres-backed job queue (Phase 1 §C, "Background processing").

Why Postgres and not Redis/Celery: free hosting can't run an always-on worker or broker, and a
queue in the same database is transactional with the data - a document row and its indexing
job commit together, so a document can never be "uploaded" without a job.

Claiming uses FOR UPDATE SKIP LOCKED, so several runners never take the same job. A claimed
job holds a lease (`locked_until`); if the process dies or the host sleeps mid-job, the lease
expires and the job is claimed again. Handlers are idempotent, so re-running is safe.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ProcessingJob
from app.services.auth_service import utcnow

# Retry backoff by attempt number (1-based). Phase 1: 1 min, 5 min, 30 min.
BACKOFF = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30)]


def enqueue(
    db: AsyncSession,
    *,
    kind: str,
    workspace_id: uuid.UUID | None,
    document_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> ProcessingJob:
    """Adds a job to the caller's transaction. Call `nudge_runner()` after commit."""
    job = ProcessingJob(
        kind=kind,
        workspace_id=workspace_id,
        document_id=document_id,
        payload=payload or {},
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    return job


_CLAIM_SQL = text(
    """
    UPDATE processing_jobs
       SET status = 'running',
           attempts = attempts + 1,
           locked_until = now() + make_interval(secs => :lease),
           updated_at = now()
     WHERE id = (
        SELECT id FROM processing_jobs
         WHERE (status IN ('queued', 'retry') AND run_after <= now())
            OR (status = 'running' AND locked_until < now())   -- expired lease: worker died
         ORDER BY run_after
         LIMIT 1
         FOR UPDATE SKIP LOCKED
     )
    RETURNING id
    """
)


async def claim_next(db: AsyncSession) -> uuid.UUID | None:
    row = (await db.execute(_CLAIM_SQL, {"lease": get_settings().job_lease_seconds})).first()
    await db.commit()
    return row[0] if row else None


async def mark_succeeded(db: AsyncSession, job_id: uuid.UUID) -> None:
    await db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(status="succeeded", locked_until=None, finished_at=utcnow(), last_error=None)
    )
    await db.commit()


async def mark_failed_or_retry(
    db: AsyncSession, job: ProcessingJob, error: str, *, permanent: bool
) -> bool:
    """Records a failure. Returns True if the job will be retried (attempts were counted at claim)."""
    retry = not permanent and job.attempts < job.max_attempts
    values: dict[str, Any] = {"last_error": error[:2000], "locked_until": None}
    if retry:
        delay = BACKOFF[min(max(job.attempts, 1), len(BACKOFF)) - 1]
        values |= {"status": "retry", "run_after": utcnow() + delay}
    else:
        values |= {"status": "failed", "finished_at": utcnow()}
    await db.execute(update(ProcessingJob).where(ProcessingJob.id == job.id).values(**values))
    await db.commit()
    return retry
