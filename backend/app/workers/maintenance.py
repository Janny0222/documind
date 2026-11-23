"""Startup maintenance.

Embeddings from different models are never comparable (Phase 1 §D), and retrieval only searches
chunks embedded by the *current* model. So when the embedding model changes - or documents were
embedded by the offline fake provider during development - their documents must be re-embedded.
This re-queues them (the index job is idempotent), once per startup.
"""

from sqlalchemy import or_, select

from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.integrations.ai import ai_configured, get_ai
from app.models import Document, Workspace
from app.workers.queue import enqueue

log = get_logger(__name__)


async def requeue_stale_embeddings(limit: int = 500) -> int:
    if not ai_configured():
        return 0
    current = get_ai().embedding_model_id
    async with get_sessionmaker()() as db:
        docs = (
            (
                await db.execute(
                    select(Document)
                    .join(Workspace, Workspace.id == Document.workspace_id)
                    .where(
                        Document.deleted_at.is_(None),
                        Document.status == "ready",
                        Workspace.ai_consent_at.is_not(None),  # never send text without consent
                        or_(
                            Document.embedding_model.is_(None), Document.embedding_model != current
                        ),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for doc in docs:
            doc.status = "queued"
            enqueue(db, kind="index_document", workspace_id=doc.workspace_id, document_id=doc.id)
        await db.commit()
    if docs:
        log.info("stale_embeddings_requeued", count=len(docs), model=current)
    return len(docs)
