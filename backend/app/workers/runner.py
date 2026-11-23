"""In-process job runner (concurrency 1).

Runs inside the API process because free hosting has no separate always-on worker. It wakes
when an upload nudges it, and also polls every few seconds for retries and expired leases.
`python -m app.workers.run` runs the same loop as a standalone worker if that's ever needed.
"""

import asyncio
import contextlib
import uuid

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.models import ProcessingJob
from app.workers import queue
from app.workers.handlers import HANDLERS, ON_GIVE_UP, PermanentJobError

log = get_logger(__name__)

_wake = asyncio.Event()
_task: asyncio.Task[None] | None = None
_drain_lock = asyncio.Lock()


def nudge_runner() -> None:
    """Tell the runner new work exists (call after the enqueuing transaction commits)."""
    _wake.set()


async def run_job(job_id: uuid.UUID) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        job = await db.get(ProcessingJob, job_id)
        if job is None:
            return
        handler = HANDLERS.get(job.kind)
        bound = log.bind(job_id=str(job.id), kind=job.kind, attempt=job.attempts)
        if handler is None:
            await queue.mark_failed_or_retry(db, job, f"No handler for {job.kind}", permanent=True)
            return
        bound.info("job_started")
        try:
            await handler(job)
        except PermanentJobError as exc:
            bound.info("job_failed_permanently", code=exc.code)
            await db.refresh(job)
            await queue.mark_failed_or_retry(db, job, f"{exc.code}: {exc}", permanent=True)
            return
        except Exception as exc:
            bound.exception("job_error", error_type=type(exc).__name__)
            await db.refresh(job)
            will_retry = await queue.mark_failed_or_retry(db, job, repr(exc), permanent=False)
            if not will_retry and (on_give_up := ON_GIVE_UP.get(job.kind)):
                await on_give_up(job)
            return
        await queue.mark_succeeded(db, job.id)
        bound.info("job_succeeded")


async def drain(max_jobs: int = 50) -> int:
    """Runs queued jobs until none are ready (or max_jobs). Returns how many ran."""
    ran = 0
    async with _drain_lock:  # concurrency 1 within this process
        while ran < max_jobs:
            async with get_sessionmaker()() as db:
                job_id = await queue.claim_next(db)
            if job_id is None:
                break
            await run_job(job_id)
            ran += 1
    return ran


async def _loop() -> None:
    poll = get_settings().job_poll_seconds
    while True:
        try:
            await drain()
        except Exception:  # never let the loop die
            log.exception("job_runner_iteration_failed")
        _wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_wake.wait(), timeout=poll)


def start_runner() -> None:
    global _task
    if _task is None and get_settings().job_runner_enabled:
        _task = asyncio.create_task(_loop(), name="documind-job-runner")
        log.info("job_runner_started")


async def stop_runner() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
