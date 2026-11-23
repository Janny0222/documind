"""Hybrid retrieval: vector similarity + Postgres full-text search, fused with Reciprocal Rank
Fusion (RRF). Keyword search catches what embeddings miss (names, numbers, clause ids); vectors
catch paraphrases.

Tenant isolation lives *inside the SQL*: every query filters on workspace_id and on the set of
document ids the server resolved for this user and scope - never on ids from the client alone.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Document, DocumentChunk

RRF_K = 60  # standard RRF constant: dampens the weight of top ranks


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    page_number: int | None
    page_unit: str
    char_start: int
    char_end: int
    content: str
    similarity: float | None = None
    keyword_hit: bool = False
    score: float = 0.0


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    best_similarity: float
    relevance_floor: float
    strong_keyword_hits: int  # chunks containing ALL the question's terms

    @property
    def found(self) -> bool:
        """Relevant enough to ask the model? Close in meaning, or an exact all-terms keyword match.
        Otherwise we answer "not found" without spending a model call."""
        return bool(self.chunks) and (
            self.best_similarity >= self.relevance_floor or self.strong_keyword_hits > 0
        )


# Columns returned by both searches, in RetrievedChunk field order.
_COLUMNS = (
    DocumentChunk.id,
    DocumentChunk.document_id,
    Document.title,
    DocumentChunk.page_number,
    Document.page_unit,
    DocumentChunk.char_start,
    DocumentChunk.char_end,
    DocumentChunk.content,
)


def _chunk(row: Any) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.id,
        document_id=row.document_id,
        document_title=row.title,
        page_number=row.page_number,
        page_unit=row.page_unit,
        char_start=row.char_start,
        char_end=row.char_end,
        content=row.content,
    )


_TERM = re.compile(r"[^\W_]{2,}", re.UNICODE)


def _any_terms_query(query_text: str) -> str | None:
    """OR-query for keyword *recall*: natural questions contain words the document doesn't
    ("period", "how"), which would make an all-terms (AND) search miss. Terms are reduced to
    letters/digits, so nothing user-supplied reaches to_tsquery's operator syntax."""
    terms = list(dict.fromkeys(t.lower() for t in _TERM.findall(query_text)))[:32]
    return " | ".join(terms) or None


async def retrieve(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    query_text: str,
    query_vector: list[float] | None,
    embedding_model: str | None,
    relevance_floor: float,
    final_k: int | None = None,
    char_budget: int | None = None,
) -> RetrievalResult:
    s = get_settings()
    if not document_ids:
        return RetrievalResult([], 0.0, relevance_floor, 0)

    base_filter = (
        DocumentChunk.workspace_id == workspace_id,
        DocumentChunk.document_id.in_(document_ids),
        Document.deleted_at.is_(None),
    )
    by_id: dict[uuid.UUID, RetrievedChunk] = {}
    vector_rank: dict[uuid.UUID, int] = {}
    keyword_rank: dict[uuid.UUID, int] = {}

    if query_vector is not None and embedding_model:
        # Iterative scan keeps returning rows until the WHERE filter is satisfied, so filtering a
        # big index down to one workspace doesn't starve the result (pgvector >= 0.8).
        await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        rows = await db.execute(
            select(*_COLUMNS, (1 - distance).label("similarity"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                *base_filter,
                DocumentChunk.embedding_model == embedding_model,
                DocumentChunk.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(s.retrieval_candidates)
        )
        for rank, row in enumerate(rows, start=1):
            chunk = _chunk(row)
            chunk.similarity = float(row.similarity)
            by_id[chunk.chunk_id] = chunk
            vector_rank[chunk.chunk_id] = rank

    english = text("'english'::regconfig")
    strong_hits = 0
    if any_terms := _any_terms_query(query_text):
        # Rank by ts_rank_cd: chunks matching more (and closer) terms come first.
        tsquery = func.to_tsquery(english, any_terms)
        rows = await db.execute(
            select(*_COLUMNS)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*base_filter, DocumentChunk.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(DocumentChunk.tsv, tsquery).desc())
            .limit(s.retrieval_candidates)
        )
        for rank, row in enumerate(rows, start=1):
            chunk = by_id.get(row.id) or _chunk(row)
            chunk.keyword_hit = True
            by_id[chunk.chunk_id] = chunk
            keyword_rank[chunk.chunk_id] = rank
        if keyword_rank:
            # Strong evidence: every term (stop words aside) appears in one chunk.
            all_terms = func.websearch_to_tsquery(english, query_text)
            strong_hits = (
                await db.execute(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(*base_filter, DocumentChunk.tsv.op("@@")(all_terms))
                )
            ).scalar_one()

    for cid, chunk in by_id.items():
        chunk.score = sum(1 / (RRF_K + r[cid]) for r in (vector_rank, keyword_rank) if cid in r)

    ranked = sorted(by_id.values(), key=lambda c: c.score, reverse=True)
    picked: list[RetrievedChunk] = []
    budget = char_budget if char_budget is not None else s.context_char_budget
    k = final_k if final_k is not None else s.retrieval_final_k
    for chunk in ranked:
        if len(picked) >= k or len(chunk.content) > budget:
            break
        picked.append(chunk)
        budget -= len(chunk.content)

    best = max((c.similarity or 0.0 for c in by_id.values()), default=0.0)
    return RetrievalResult(picked, best, relevance_floor, strong_hits)
