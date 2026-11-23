"""Semantic search: the retrieval half of RAG without the model call.

Returns ranked passages (with exact page and character offsets) so users can jump straight to
the source. Same tenant guarantees as chat: the scope is resolved server-side and retrieval
filters by workspace inside SQL. Without AI consent (or with the provider down / out of quota)
it degrades to keyword-only search instead of failing.
"""

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.ai import AIError, AIQuotaError, ai_configured, get_ai
from app.models import Document
from app.rag.retrieval import retrieve
from app.schemas.insights import SearchHit, SearchResponse
from app.services.chat_service import resolve_scope, validate_scope
from app.services.document_service import TYPE_BY_MIME
from app.services.usage_service import record_usage
from app.services.workspace_service import WorkspaceContext

log = get_logger(__name__)


async def search(
    db: AsyncSession, ctx: WorkspaceContext, query: str, scope: dict[str, object], limit: int
) -> SearchResponse:
    await validate_scope(db, ctx, scope)
    doc_ids = await resolve_scope(db, ctx, scope)
    if not doc_ids:
        return SearchResponse(query=query, mode="keyword", hits=[])

    ai = get_ai() if ai_configured() else None
    vector: list[float] | None = None
    mode = "keyword"
    if ai is not None and ctx.workspace.ai_consent_at is not None:
        started = time.perf_counter()
        status = "ok"
        result = None
        try:
            result = await ai.embed([query], "query")
            vector, mode = result.vectors[0], "hybrid"
        except AIQuotaError:
            status = "rate_limited"
        except AIError:
            status = "error"
        record_usage(
            db,
            workspace_id=ctx.id,
            user_id=ctx.user.id,
            operation="embed_query",
            model=ai.embedding_model_id,
            usage=result.usage if result else None,
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        await db.commit()
        if status != "ok":
            log.info("search_degraded_to_keyword", reason=status)

    found = await retrieve(
        db,
        workspace_id=ctx.id,
        document_ids=doc_ids,
        query_text=query,
        query_vector=vector,
        embedding_model=ai.embedding_model_id if ai else None,
        relevance_floor=ai.relevance_floor if ai else 1.0,
        final_k=limit,
        char_budget=10**9,  # no prompt to fit: rank-only cut
    )
    # Search shows everything that matched; low-similarity-only hits are dropped so noise
    # doesn't bury the real results.
    floor = ai.relevance_floor if ai else 1.0
    chunks = [c for c in found.chunks if c.keyword_hit or (c.similarity or 0.0) >= floor * 0.9]
    mimes = (
        dict(
            (
                await db.execute(
                    select(Document.id, Document.mime_type).where(
                        Document.id.in_({c.document_id for c in chunks})
                    )
                )
            ).all()
        )
        if chunks
        else {}
    )
    hits = [
        SearchHit(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            document_title=c.document_title,
            file_type=TYPE_BY_MIME.get(mimes.get(c.document_id, ""), "txt"),
            page_number=c.page_number,
            page_unit=c.page_unit,
            char_start=c.char_start,
            char_end=c.char_end,
            text=c.content,
            score=round(c.score, 5),
            similarity=round(c.similarity, 4) if c.similarity is not None else None,
            keyword_match=c.keyword_hit,
        )
        for c in chunks
    ]
    return SearchResponse(query=query, mode=mode, hits=hits)
