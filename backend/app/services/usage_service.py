"""AI usage ledger and limits.

Every provider call writes one row (tokens, model, latency, outcome). Token counts come from the
provider when it reports them. `est_cost_usd` uses configured list prices and is an *estimate*,
never billing data. Daily caps are counted here in Postgres, so they survive restarts.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import TooManyRequests
from app.integrations.ai import Usage
from app.models import AIUsageRecord


def estimate_cost(operation: str, usage: Usage) -> Decimal:
    s = get_settings()
    if operation.startswith("embed"):
        dollars = usage.input_tokens * s.price_embedding_per_m / 1_000_000
    else:
        dollars = (
            usage.input_tokens * s.price_chat_input_per_m
            + usage.output_tokens * s.price_chat_output_per_m
        ) / 1_000_000
    return Decimal(str(round(dollars, 6)))


def record_usage(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    operation: str,
    model: str,
    usage: Usage | None,
    status: str = "ok",
    latency_ms: int | None = None,
) -> None:
    usage = usage or Usage()
    db.add(
        AIUsageRecord(
            workspace_id=workspace_id,
            user_id=user_id,
            operation=operation,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            est_cost_usd=estimate_cost(operation, usage),
            status=status,
            latency_ms=latency_ms,
        )
    )


def _start_of_day_utc() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def questions_today(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID | None = None
) -> int:
    conditions = [
        AIUsageRecord.user_id == user_id,
        AIUsageRecord.operation == "chat",
        AIUsageRecord.status == "ok",
        AIUsageRecord.created_at >= _start_of_day_utc(),
    ]
    if workspace_id is not None:
        conditions.append(AIUsageRecord.workspace_id == workspace_id)
    return (await db.execute(select(func.count()).where(*conditions))).scalar_one()


async def question_quota(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, is_demo: bool
) -> tuple[int, int]:
    """(limit, used) that applies to this user in this workspace today. The shared demo has its
    own smaller cap, counted inside the demo only; the overall per-user cap still applies."""
    s = get_settings()
    overall = (s.ai_daily_questions_per_user, await questions_today(db, user_id))
    if not is_demo:
        return overall
    demo = (s.ai_daily_questions_demo, await questions_today(db, user_id, workspace_id))
    # Whichever has fewer questions left is the one that binds.
    return min(overall, demo, key=lambda q: q[0] - q[1])


async def enforce_daily_question_limit(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, is_demo: bool = False
) -> int:
    """Raises 429 when the user has used today's questions. Returns how many remain."""
    limit, used = await question_quota(db, user_id, workspace_id, is_demo)
    if used >= limit:
        where = (
            " in the demo workspace"
            if is_demo and limit < get_settings().ai_daily_questions_per_user
            else ""
        )
        raise TooManyRequests(
            f"You've used all {limit} AI questions for today{where}. The limit resets at midnight UTC.",
            code="daily_question_limit",
        )
    return limit - used
