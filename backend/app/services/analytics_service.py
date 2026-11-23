"""Usage & analytics for workspace admins (Phase 1 §13).

All numbers come from the workspace's own rows (ai_usage_records, messages, documents).
Token counts are provider-reported where available; cost is an *estimate* from configured
prices and is labelled as such in the API and UI - it is not billing data.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AIUsageRecord, Conversation, Document, Message, User
from app.schemas.insights import (
    Analytics,
    DailyUsage,
    DocumentStats,
    MemberUsage,
    OperationUsage,
    UsageError,
    UsageTotals,
)
from app.services.document_service import TYPE_BY_MIME
from app.services.workspace_service import WorkspaceContext


async def workspace_analytics(db: AsyncSession, ctx: WorkspaceContext, days: int) -> Analytics:
    s = get_settings()
    since_day = datetime.now(UTC).date() - timedelta(days=days - 1)
    since = datetime.combine(since_day, datetime.min.time(), tzinfo=UTC)
    in_range = (AIUsageRecord.workspace_id == ctx.id, AIUsageRecord.created_at >= since)
    is_question = AIUsageRecord.operation == "chat"

    # ---- totals
    row = (
        await db.execute(
            select(
                func.count().filter(is_question),
                func.count().filter(is_question, AIUsageRecord.status == "rate_limited"),
                func.count().filter(
                    is_question, AIUsageRecord.status.in_(("error", "quota_exhausted"))
                ),
                func.coalesce(func.sum(AIUsageRecord.input_tokens), 0),
                func.coalesce(func.sum(AIUsageRecord.output_tokens), 0),
                func.coalesce(func.sum(AIUsageRecord.est_cost_usd), 0),
            ).where(*in_range)
        )
    ).one()
    questions, rate_limited, failed, tokens_in, tokens_out, cost = row
    msg_counts = dict(
        (
            await db.execute(
                select(Message.status, func.count())
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.workspace_id == ctx.id,
                    Message.role == "assistant",
                    Message.created_at >= since,
                )
                .group_by(Message.status)
            )
        ).all()
    )
    totals = UsageTotals(
        questions=questions,
        answered=msg_counts.get("complete", 0),
        not_found=msg_counts.get("not_found", 0),
        failed=failed,
        rate_limited=rate_limited,
        input_tokens=int(tokens_in),
        output_tokens=int(tokens_out),
        est_cost_usd=float(cost),
    )

    # ---- per day (every day present, zeros included, so charts have no gaps)
    day = cast(func.timezone("UTC", AIUsageRecord.created_at), Date)
    per_day = {
        d: (q, i, o)
        for d, q, i, o in (
            await db.execute(
                select(
                    day,
                    func.count().filter(is_question),
                    func.sum(AIUsageRecord.input_tokens),
                    func.sum(AIUsageRecord.output_tokens),
                )
                .where(*in_range)
                .group_by(day)
            )
        ).all()
    }
    daily = []
    for n in range(days):
        d: date = since_day + timedelta(days=n)
        q, i, o = per_day.get(d, (0, 0, 0))
        daily.append(
            DailyUsage(date=d, questions=q, input_tokens=int(i or 0), output_tokens=int(o or 0))
        )

    # ---- by operation
    by_operation = [
        OperationUsage(
            operation=op,
            calls=calls,
            input_tokens=int(i or 0),
            output_tokens=int(o or 0),
            errors=errs,
        )
        for op, calls, i, o, errs in (
            await db.execute(
                select(
                    AIUsageRecord.operation,
                    func.count(),
                    func.sum(AIUsageRecord.input_tokens),
                    func.sum(AIUsageRecord.output_tokens),
                    func.count().filter(AIUsageRecord.status != "ok"),
                )
                .where(*in_range)
                .group_by(AIUsageRecord.operation)
                .order_by(func.count().desc())
            )
        ).all()
    ]

    # ---- documents (current state, plus uploads in range)
    live = (Document.workspace_id == ctx.id, Document.deleted_at.is_(None))
    drow = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Document.status == "ready"),
                func.count().filter(Document.status.in_(("uploaded", "queued", "processing"))),
                func.count().filter(Document.status == "failed"),
                func.coalesce(func.sum(Document.size_bytes), 0),
                func.count().filter(Document.created_at >= since),
            ).where(*live)
        )
    ).one()
    by_type = {"pdf": 0, "docx": 0, "txt": 0}
    for mime, n in (
        await db.execute(
            select(Document.mime_type, func.count()).where(*live).group_by(Document.mime_type)
        )
    ).all():
        by_type[TYPE_BY_MIME.get(mime, "txt")] += n
    documents = DocumentStats(
        total=drow[0],
        ready=drow[1],
        processing=drow[2],
        failed=drow[3],
        storage_bytes=int(drow[4]),
        by_type=by_type,
        uploads_in_range=drow[5],
    )

    # ---- who asks most (members only see this through admin-only analytics)
    top_members = [
        MemberUsage(user_id=uid, display_name=name or "Former member", questions=n)
        for uid, name, n in (
            await db.execute(
                select(AIUsageRecord.user_id, User.display_name, func.count())
                .outerjoin(User, User.id == AIUsageRecord.user_id)
                .where(*in_range, is_question)
                .group_by(AIUsageRecord.user_id, User.display_name)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
    ]

    recent_errors = [
        UsageError(created_at=at, operation=op, status=st, model=model)
        for at, op, st, model in (
            await db.execute(
                select(
                    AIUsageRecord.created_at,
                    AIUsageRecord.operation,
                    AIUsageRecord.status,
                    AIUsageRecord.model,
                )
                .where(*in_range, AIUsageRecord.status != "ok")
                .order_by(AIUsageRecord.created_at.desc())
                .limit(10)
            )
        ).all()
    ]

    return Analytics(
        days=days,
        since=since_day,
        totals=totals,
        daily=daily,
        by_operation=by_operation,
        documents=documents,
        top_members=top_members,
        recent_errors=recent_errors,
        limits={
            "daily_questions_per_user": s.ai_daily_questions_per_user,
            "max_documents": s.max_documents_per_workspace,
            "max_upload_mb": s.max_upload_mb,
            "max_chunks": s.max_chunks_per_workspace,
        },
    )
