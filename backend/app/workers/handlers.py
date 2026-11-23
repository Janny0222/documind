"""Job handlers. Each one is idempotent: running it twice leaves the same result."""

import asyncio
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.integrations.ai import AIError, AIQuotaError, ai_configured, get_ai
from app.integrations.storage import get_storage
from app.models import Document, DocumentChunk, DocumentPage, ProcessingJob, Workspace
from app.rag.chunking import Chunk, chunk_pages
from app.rag.parsing import ParsedDocument, parse_document
from app.rag.validation import ValidationError, kind_from_filename
from app.services.activity import record_activity
from app.services.auth_service import utcnow
from app.services.notification_service import notify
from app.services.usage_service import record_usage

log = get_logger(__name__)


class PermanentJobError(Exception):
    """A failure that retrying can't fix (bad file, limit reached). Not retried."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ index_document


async def index_document(job: ProcessingJob) -> None:
    s = get_settings()
    assert job.document_id is not None
    async with get_sessionmaker()() as db:
        doc = await db.get(Document, job.document_id)
        if doc is None or doc.deleted_at is not None:
            return  # deleted while queued - nothing to do
        storage_key, filename = doc.storage_key, doc.original_filename
        workspace = await db.get(Workspace, doc.workspace_id)
        consented = workspace is not None and workspace.ai_consent_at is not None
        uploader = doc.uploaded_by
        doc.status, doc.error_code, doc.error_message = "processing", None, None
        await db.commit()

    try:
        parsed = await _download_and_parse(storage_key, filename, s.max_pages_per_document)
    except ValidationError as exc:
        await _fail_document(job.document_id, exc.code, exc.message)
        raise PermanentJobError(exc.code, exc.message) from exc

    if parsed.total_chars < s.min_text_chars:
        message = (
            "We couldn't find any text in this file. If it's a scanned PDF, it needs OCR, "
            "which isn't supported yet."
        )
        await _fail_document(job.document_id, "no_text", message)
        raise PermanentJobError("no_text", message)

    chunks = chunk_pages(parsed.pages, size=s.chunk_size_chars, overlap=s.chunk_overlap_chars)

    # Text only leaves the server after a workspace admin consented (Phase 1 decision #5).
    # Without consent the document is still indexed for keyword search, just not embedded.
    vectors: list[list[float]] | None = None
    if consented and ai_configured():
        vectors = await _embed_chunks(job, chunks, uploader)

    async with get_sessionmaker()() as db:
        doc = await db.get(Document, job.document_id, with_for_update=True)
        if doc is None or doc.deleted_at is not None:
            return
        existing = (
            await db.execute(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.workspace_id == doc.workspace_id,
                    DocumentChunk.document_id != doc.id,
                )
            )
        ).scalar_one()
        if existing + len(chunks) > s.max_chunks_per_workspace:
            message = "This workspace has reached its storage limit for indexed text. Delete some documents first."
            await _fail_in_tx(db, doc, "workspace_chunk_limit", message)
            raise PermanentJobError("workspace_chunk_limit", message)

        first_index = doc.indexed_at is None
        ai = get_ai() if vectors is not None else None
        await _replace_index(
            db, doc, parsed, chunks, vectors, ai.embedding_model_id if ai else None
        )
        doc.status = "ready"
        doc.page_count = len(parsed.pages)
        doc.page_unit = parsed.unit
        doc.chunk_count = len(chunks)
        doc.indexed_at = utcnow()
        doc.error_code = doc.error_message = None
        doc.embedding_model = ai.embedding_model_id if ai else None
        record_activity(
            db,
            workspace_id=doc.workspace_id,
            actor_id=doc.uploaded_by,
            action="document.indexed",
            target_type="document",
            target_id=doc.id,
            meta={"pages": len(parsed.pages), "chunks": len(chunks)},
        )
        if first_index and doc.uploaded_by:
            notify(
                db,
                user_id=doc.uploaded_by,
                workspace_id=doc.workspace_id,
                kind="document_ready",
                title=f"“{doc.title}” is ready",
                body=f"{len(parsed.pages)} {parsed.unit}{'s' if len(parsed.pages) != 1 else ''} indexed.",
                link=f"/w/{doc.workspace_id}/documents?doc={doc.id}",
            )
        await db.commit()
    log.info(
        "document_indexed",
        document_id=str(job.document_id),
        pages=len(parsed.pages),
        chunks=len(chunks),
    )


async def _download_and_parse(storage_key: str, filename: str, max_pages: int) -> ParsedDocument:
    kind = kind_from_filename(filename)
    with tempfile.TemporaryDirectory(prefix="documind-") as tmp:
        path = Path(tmp) / f"source.{kind.value}"
        await get_storage().download_to(storage_key, path)
        # Parsing is CPU-bound: run it off the event loop so the API stays responsive.
        return await asyncio.to_thread(parse_document, path, kind, max_pages=max_pages)


async def _embed_chunks(
    job: ProcessingJob, chunks: list[Chunk], uploader: uuid.UUID | None
) -> list[list[float]]:
    """Embeds in batches. Quota errors propagate so the job retries later with backoff -
    we never fall back to paid usage or partially-embedded documents."""
    s = get_settings()
    ai = get_ai()
    vectors: list[list[float]] = []
    assert job.workspace_id is not None
    for i in range(0, len(chunks), s.embedding_batch_size):
        batch = [c.content for c in chunks[i : i + s.embedding_batch_size]]
        started = time.perf_counter()
        status = "ok"
        result = None
        try:
            result = await ai.embed(batch, "document")
        except AIQuotaError:
            status = "rate_limited"
            raise
        except AIError:
            status = "error"
            raise
        finally:
            async with get_sessionmaker()() as db:
                record_usage(
                    db,
                    workspace_id=job.workspace_id,
                    user_id=uploader,
                    operation="embed_document",
                    model=ai.embedding_model_id,
                    usage=result.usage if result else None,
                    status=status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                await db.commit()
        vectors.extend(result.vectors)
    return vectors


async def _replace_index(
    db: AsyncSession,
    doc: Document,
    parsed: ParsedDocument,
    chunks: list[Chunk],
    vectors: list[list[float]] | None = None,
    embedding_model: str | None = None,
) -> None:
    """Delete-then-insert in one transaction: re-indexing never leaves duplicates or a half index."""
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    await db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
    if parsed.pages:
        await db.execute(
            insert(DocumentPage),
            [
                {"document_id": doc.id, "page_number": i, "text": t}
                for i, t in enumerate(parsed.pages, start=1)
            ],
        )
    if chunks:
        await db.execute(
            insert(DocumentChunk),
            [
                {
                    "id": uuid.uuid4(),
                    "workspace_id": doc.workspace_id,
                    "document_id": doc.id,
                    "chunk_index": i,
                    "page_number": c.page_number,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "content": c.content,
                    "token_count": c.token_estimate,
                    "embedding": vectors[i] if vectors else None,
                    "embedding_model": embedding_model if vectors else None,
                }
                for i, c in enumerate(chunks)
            ],
        )


async def _fail_in_tx(db: AsyncSession, doc: Document, code: str, message: str) -> None:
    doc.status, doc.error_code, doc.error_message = "failed", code, message[:500]
    if doc.uploaded_by:
        notify(
            db,
            user_id=doc.uploaded_by,
            workspace_id=doc.workspace_id,
            kind="document_failed",
            title=f"“{doc.title}” couldn't be processed",
            body=message[:300],
            link=f"/w/{doc.workspace_id}/documents?doc={doc.id}",
        )
    record_activity(
        db,
        workspace_id=doc.workspace_id,
        actor_id=doc.uploaded_by,
        action="document.failed",
        target_type="document",
        target_id=doc.id,
        meta={"code": code},
    )
    await db.commit()


async def _fail_document(document_id: uuid.UUID, code: str, message: str) -> None:
    async with get_sessionmaker()() as db:
        doc = await db.get(Document, document_id)
        if doc is not None and doc.deleted_at is None:
            await _fail_in_tx(db, doc, code, message)


async def index_document_gave_up(job: ProcessingJob) -> None:
    """Transient errors exhausted their retries: tell the user instead of spinning forever."""
    if job.document_id:
        await _fail_document(
            job.document_id,
            "processing_error",
            "Something went wrong while processing this file. Try again in a few minutes.",
        )


# ------------------------------------------------------------------ purge jobs


async def purge_document(job: ProcessingJob) -> None:
    key = job.payload.get("storage_key")
    if key:
        await get_storage().delete(str(key))
    if job.document_id:
        async with get_sessionmaker()() as db:
            await db.execute(
                delete(Document).where(
                    Document.id == job.document_id, Document.deleted_at.is_not(None)
                )
            )
            await db.commit()


async def purge_workspace(job: ProcessingJob) -> None:
    prefix = job.payload.get("prefix")
    if prefix:
        await get_storage().delete_prefix(str(prefix))


HANDLERS: dict[str, Callable[[ProcessingJob], Awaitable[None]]] = {
    "index_document": index_document,
    "purge_document": purge_document,
    "purge_workspace": purge_workspace,
}

ON_GIVE_UP: dict[str, Callable[[ProcessingJob], Awaitable[None]]] = {
    "index_document": index_document_gave_up,
}
