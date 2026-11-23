"""Conversations and grounded question answering (the RAG query flow, Phase 1 §C).

Checks that can fail (auth, consent, daily limit, scope) run *before* streaming starts, so they
become normal HTTP errors. The stream itself then emits Server-Sent Events:

  meta        {user_message_id, assistant_message_id}
  retrieval   {documents, passages}           - "searching N documents"
  token       {text}                          - answer text as it's generated
  citations   [CitationOut...]                - verified sources actually cited
  suggestions [str...]                        - follow-up questions
  done        {message: MessageOut}           - final stored message (cleaned text)
  error       {code, message}                 - quota / provider problems mid-stream
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.integrations.ai import AIError, AIQuotaError, ChatTurn, Usage, ai_configured, get_ai
from app.models import (
    Collection,
    CollectionDocument,
    Conversation,
    Document,
    DocumentChunk,
    Message,
    MessageCitation,
    Role,
)
from app.rag import prompts
from app.rag.citations import FollowUpSplitter, verify_citations
from app.rag.retrieval import RetrievedChunk, retrieve
from app.schemas.chat import (
    AiStatus,
    CitationOut,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.services.auth_service import utcnow
from app.services.usage_service import (
    enforce_daily_question_limit,
    question_quota,
    record_usage,
)
from app.services.workspace_service import WorkspaceContext

log = get_logger(__name__)
HISTORY_TURNS = 6


class AIConsentRequired(AppError):
    status_code, code, title = 403, "ai_consent_required", "AI processing isn't enabled"


class AINotConfigured(AppError):
    status_code, code, title = 503, "ai_not_configured", "AI isn't configured"


# ------------------------------------------------------------------ conversations


def _conv_out(c: Conversation) -> ConversationOut:
    return ConversationOut.model_validate(
        {
            "id": c.id,
            "title": c.title,
            "scope": c.scope,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
    )


async def get_conversation(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID
) -> Conversation:
    """Conversations are private to their creator (MVP decision): others get 404."""
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == ctx.id,
                Conversation.user_id == ctx.user.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise NotFound("Conversation not found")
    return conv


async def list_conversations(db: AsyncSession, ctx: WorkspaceContext) -> list[ConversationOut]:
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.workspace_id == ctx.id, Conversation.user_id == ctx.user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        )
    ).scalars()
    return [_conv_out(c) for c in rows]


async def create_conversation(
    db: AsyncSession, ctx: WorkspaceContext, scope: dict[str, Any], title: str | None
) -> ConversationOut:
    await validate_scope(db, ctx, scope)
    conv = Conversation(
        workspace_id=ctx.id, user_id=ctx.user.id, title=title or "New conversation", scope=scope
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return _conv_out(conv)


async def update_conversation(
    db: AsyncSession,
    ctx: WorkspaceContext,
    conversation_id: uuid.UUID,
    title: str | None,
    scope: dict[str, Any] | None,
) -> ConversationOut:
    conv = await get_conversation(db, ctx, conversation_id)
    if title is not None:
        conv.title = title
    if scope is not None:
        await validate_scope(db, ctx, scope)
        conv.scope = scope
    await db.commit()
    await db.refresh(conv)
    return _conv_out(conv)


async def delete_conversation(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID
) -> None:
    conv = await get_conversation(db, ctx, conversation_id)
    await db.delete(conv)
    await db.commit()


async def _citations_for(
    db: AsyncSession, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[CitationOut]]:
    if not message_ids:
        return {}
    rows = await db.execute(
        select(
            MessageCitation, DocumentChunk.char_start, DocumentChunk.char_end, Document.page_unit
        )
        .outerjoin(DocumentChunk, DocumentChunk.id == MessageCitation.chunk_id)
        .outerjoin(Document, Document.id == MessageCitation.document_id)
        .where(MessageCitation.message_id.in_(message_ids))
        .order_by(MessageCitation.marker)
    )
    out: dict[uuid.UUID, list[CitationOut]] = {}
    for cit, start, end, unit in rows:
        out.setdefault(cit.message_id, []).append(
            CitationOut(
                marker=cit.marker,
                document_id=cit.document_id,
                document_title=cit.document_title,
                page_number=cit.page_number,
                page_unit=unit or "page",
                excerpt=cit.excerpt,
                chunk_id=cit.chunk_id,
                char_start=start,
                char_end=end,
            )
        )
    return out


def _message_out(m: Message, citations: list[CitationOut]) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        status=m.status,
        created_at=m.created_at,
        citations=citations,
    )


async def conversation_detail(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID
) -> ConversationDetail:
    conv = await get_conversation(db, ctx, conversation_id)
    messages = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at, Message.id)
            )
        ).scalars()
    )
    cites = await _citations_for(db, [m.id for m in messages])
    base = _conv_out(conv)
    return ConversationDetail(
        **base.model_dump(), messages=[_message_out(m, cites.get(m.id, [])) for m in messages]
    )


# ------------------------------------------------------------------ scope & status


async def resolve_scope(
    db: AsyncSession, ctx: WorkspaceContext, scope: dict[str, Any]
) -> list[uuid.UUID]:
    """Turns a scope into the READY document ids this workspace actually owns. Ids from another
    workspace simply don't match, so they can't widen the search."""
    q = select(Document.id).where(
        Document.workspace_id == ctx.id, Document.deleted_at.is_(None), Document.status == "ready"
    )
    kind = scope.get("type", "workspace")
    if kind == "collection":
        q = q.where(
            Document.id.in_(
                select(CollectionDocument.document_id).where(
                    CollectionDocument.collection_id == uuid.UUID(str(scope["id"])),
                    CollectionDocument.workspace_id == ctx.id,
                )
            )
        )
    elif kind == "documents":
        q = q.where(Document.id.in_([uuid.UUID(str(i)) for i in scope.get("ids", [])]))
    return list((await db.execute(q)).scalars())


async def validate_scope(db: AsyncSession, ctx: WorkspaceContext, scope: dict[str, Any]) -> None:
    """A scope may only name this workspace's collection/documents; anything else is a 404
    (same answer whether it doesn't exist or belongs to someone else)."""
    kind = scope.get("type", "workspace")
    if kind == "collection":
        found = (
            await db.execute(
                select(Collection.id).where(
                    Collection.id == uuid.UUID(str(scope["id"])), Collection.workspace_id == ctx.id
                )
            )
        ).first()
        if found is None:
            raise NotFound("Collection not found")
    elif kind == "documents":
        ids = {uuid.UUID(str(i)) for i in scope.get("ids", [])}
        found_ids = set(
            (
                await db.execute(
                    select(Document.id).where(
                        Document.id.in_(ids),
                        Document.workspace_id == ctx.id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        if found_ids != ids:
            raise NotFound("One or more documents were not found")


async def ai_status(db: AsyncSession, ctx: WorkspaceContext) -> AiStatus:
    limit, used = await question_quota(db, ctx.user.id, ctx.id, ctx.workspace.is_demo)
    return AiStatus(
        configured=ai_configured(),
        consent=ctx.workspace.ai_consent_at is not None,
        questions_left_today=max(0, limit - used),
        daily_limit=limit,
        chat_model=get_ai().chat_model if ai_configured() else "",
    )


# ------------------------------------------------------------------ asking


@dataclass
class PreparedQuestion:
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    question: str
    user_message_id: uuid.UUID
    document_ids: list[uuid.UUID]
    history: list[tuple[str, str]]


async def _preflight(db: AsyncSession, ctx: WorkspaceContext) -> None:
    if not ai_configured():
        raise AINotConfigured("The AI provider isn't configured on this server.")
    if ctx.workspace.ai_consent_at is None:
        raise AIConsentRequired(
            "A workspace admin needs to allow AI processing before you can ask questions."
        )
    if not ctx.role.at_least(Role.VIEWER):  # defensive; every member is at least a viewer
        raise Forbidden()
    await enforce_daily_question_limit(db, ctx.user.id, ctx.id, ctx.workspace.is_demo)


async def _history(
    db: AsyncSession, conversation_id: uuid.UUID, before: uuid.UUID | None = None
) -> list[tuple[str, str]]:
    q = select(Message.role, Message.content).where(
        Message.conversation_id == conversation_id, Message.status.in_(("complete", "not_found"))
    )
    if before is not None:
        q = q.where(Message.id != before)
    rows = (await db.execute(q.order_by(Message.created_at.desc()).limit(HISTORY_TURNS))).all()
    return [(r, c) for r, c in reversed(rows)]


async def prepare_question(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID, content: str
) -> PreparedQuestion:
    conv = await get_conversation(db, ctx, conversation_id)
    await _preflight(db, ctx)
    doc_ids = await resolve_scope(db, ctx, conv.scope)
    history = await _history(db, conv.id)
    msg = Message(conversation_id=conv.id, role="user", content=content, status="complete")
    db.add(msg)
    if conv.title == "New conversation":
        conv.title = content[:80] + ("…" if len(content) > 80 else "")
    conv.updated_at = utcnow()
    await db.commit()
    return PreparedQuestion(ctx.id, ctx.user.id, conv.id, content, msg.id, doc_ids, history)


async def prepare_regenerate(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> PreparedQuestion:
    """Regenerate the latest assistant answer: drop it and answer its question again."""
    conv = await get_conversation(db, ctx, conversation_id)
    last = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if (
        not last
        or last[0].id != message_id
        or last[0].role != "assistant"
        or len(last) < 2
        or last[1].role != "user"
    ):
        raise Conflict("Only the latest answer can be regenerated", code="not_latest_answer")
    await _preflight(db, ctx)
    question = last[1]
    await db.delete(last[0])
    await db.commit()
    doc_ids = await resolve_scope(db, ctx, conv.scope)
    history = await _history(db, conv.id, before=question.id)
    return PreparedQuestion(
        ctx.id, ctx.user.id, conv.id, question.content, question.id, doc_ids, history
    )


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


async def answer_stream(p: PreparedQuestion) -> AsyncIterator[str]:
    """The streaming half. Uses its own DB sessions: the request's session may close before the
    stream finishes."""
    ai = get_ai()
    sessionmaker = get_sessionmaker()
    assistant_id = uuid.uuid4()
    yield sse("meta", {"user_message_id": p.user_message_id, "assistant_message_id": assistant_id})

    answer_text = ""
    status = "failed"
    chunks: list[RetrievedChunk] = []
    marker_map: list[tuple[str, RetrievedChunk]] = []
    usage = Usage()
    started = time.perf_counter()
    try:
        # 1. Follow-ups become standalone questions, so retrieval sees the full intent.
        search_query = p.question
        if p.history and get_settings().ai_rewrite_followups:
            try:
                rewritten, rw_usage = await ai.complete(
                    prompts.REWRITE_SYSTEM, prompts.rewrite_prompt(p.history, p.question)
                )
                search_query = rewritten or p.question
                async with sessionmaker() as db:
                    record_usage(
                        db,
                        workspace_id=p.workspace_id,
                        user_id=p.user_id,
                        operation="rewrite_query",
                        model=ai.chat_model,
                        usage=rw_usage,
                    )
                    await db.commit()
            except AIError:
                search_query = f"{p.history[-1][1][:200]} {p.question}" if p.history else p.question

        # 2. Embed the query and retrieve (vector + keyword), filtered to this workspace/scope.
        q_vec = None
        if p.document_ids:
            q = await ai.embed([search_query], "query")
            q_vec = q.vectors[0]
            async with sessionmaker() as db:
                record_usage(
                    db,
                    workspace_id=p.workspace_id,
                    user_id=p.user_id,
                    operation="embed_query",
                    model=ai.embedding_model_id,
                    usage=q.usage,
                )
                await db.commit()
        async with sessionmaker() as db:
            result = await retrieve(
                db,
                workspace_id=p.workspace_id,
                document_ids=p.document_ids,
                query_text=search_query,
                query_vector=q_vec,
                embedding_model=ai.embedding_model_id,
                relevance_floor=ai.relevance_floor,
            )
            await db.commit()
        chunks = result.chunks
        yield sse("retrieval", {"documents": len(p.document_ids), "passages": len(chunks)})

        # 3. Nothing relevant: answer "not found" without spending a model call.
        if not result.found:
            answer_text = prompts.NOT_FOUND
            if not p.document_ids:
                answer_text += " There are no ready documents in this scope yet."
            yield sse("token", {"text": answer_text})
            status = "not_found"
            chunks = []
        else:
            # 4. Grounded generation, streamed.
            turns = [ChatTurn("user" if r == "user" else "model", t) for r, t in p.history]
            turns.append(ChatTurn("user", prompts.answer_prompt(p.question, chunks)))
            splitter = FollowUpSplitter()
            suggestions: list[str] = []
            async for event in ai.stream(prompts.SYSTEM, turns):
                if event.final:
                    usage = event.usage or usage
                    continue
                visible = splitter.feed(event.text)
                if visible:
                    yield sse("token", {"text": visible})
            rest, suggestions = splitter.finish()
            if rest:
                yield sse("token", {"text": rest})
            verified = verify_citations(splitter.answer, chunks)
            answer_text = verified.text
            status = "not_found" if verified.not_found else "complete"
            if verified.invalid_markers:
                log.info("invalid_citations_removed", count=verified.invalid_markers)
            used = verified.used
            citations = [_citation_out(marker, c) for marker, c in used]
            yield sse("citations", [c.model_dump(mode="json") for c in citations])
            if suggestions and status == "complete":
                yield sse("suggestions", suggestions)
            marker_map = used
    except AIQuotaError:
        await _record_chat(p, ai.chat_model, usage, "rate_limited", started)
        yield sse(
            "error",
            {
                "code": "ai_rate_limited",
                "message": "The AI service is busy or today's free quota is used up. Try again in a few minutes.",
            },
        )
        await _save_assistant(p, assistant_id, answer_text, "failed", [])
        return
    except AIError:
        await _record_chat(p, ai.chat_model, usage, "error", started)
        yield sse(
            "error",
            {
                "code": "ai_unavailable",
                "message": "The AI service isn't responding. Try again shortly.",
            },
        )
        await _save_assistant(p, assistant_id, answer_text, "failed", [])
        return
    except asyncio.CancelledError:
        # Client went away mid-stream: keep what we have, marked as failed.
        await asyncio.shield(_save_assistant(p, assistant_id, answer_text, "failed", []))
        raise

    await _record_chat(p, ai.chat_model, usage, "ok", started)
    saved = await _save_assistant(
        p, assistant_id, answer_text, status, marker_map if status == "complete" else []
    )
    yield sse("done", {"message": saved.model_dump(mode="json")})


def _citation_out(marker: str, c: RetrievedChunk) -> CitationOut:
    return CitationOut(
        marker=marker,
        document_id=c.document_id,
        document_title=c.document_title,
        page_number=c.page_number,
        page_unit=c.page_unit,
        excerpt=c.content[:600],
        chunk_id=c.chunk_id,
        char_start=c.char_start,
        char_end=c.char_end,
    )


async def _record_chat(
    p: PreparedQuestion, model: str, usage: Usage, status: str, started: float
) -> None:
    async with get_sessionmaker()() as db:
        record_usage(
            db,
            workspace_id=p.workspace_id,
            user_id=p.user_id,
            operation="chat",
            model=model,
            usage=usage,
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        await db.commit()


async def _save_assistant(
    p: PreparedQuestion,
    message_id: uuid.UUID,
    text: str,
    status: str,
    used: list[tuple[str, RetrievedChunk]],
) -> MessageOut:
    async with get_sessionmaker()() as db:
        msg = Message(
            id=message_id,
            conversation_id=p.conversation_id,
            role="assistant",
            content=text.strip(),
            status=status,
            model=get_ai().chat_model,
        )
        db.add(msg)
        for marker, c in used:
            # Snapshot title/page/excerpt: the answer stays readable even if the document is deleted.
            db.add(
                MessageCitation(
                    message_id=message_id,
                    marker=marker,
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    document_title=c.document_title[:255],
                    page_number=c.page_number,
                    excerpt=c.content[:1200],
                )
            )
        conv = await db.get(Conversation, p.conversation_id)
        if conv is not None:
            conv.updated_at = utcnow()
        await db.commit()
        await db.refresh(msg)
        cites = await _citations_for(db, [msg.id])
        return _message_out(msg, cites.get(msg.id, []))
