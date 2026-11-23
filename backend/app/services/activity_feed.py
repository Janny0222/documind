from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, User
from app.schemas.insights import ActivityItem, ActivityPage
from app.services.workspace_service import WorkspaceContext


async def list_activity(
    db: AsyncSession, ctx: WorkspaceContext, *, limit: int, before: datetime | None
) -> ActivityPage:
    """Newest first, keyset-paginated by created_at (stable while new events arrive)."""
    q = (
        select(ActivityLog, User.display_name)
        .outerjoin(User, User.id == ActivityLog.actor_id)
        .where(ActivityLog.workspace_id == ctx.id)
    )
    if before is not None:
        q = q.where(ActivityLog.created_at < before)
    rows = (await db.execute(q.order_by(ActivityLog.created_at.desc()).limit(limit + 1))).all()
    items = [
        ActivityItem(
            id=a.id,
            action=a.action,
            actor=name,
            target_type=a.target_type,
            target_id=a.target_id,
            meta=a.meta or {},
            created_at=a.created_at,
        )
        for a, name in rows[:limit]
    ]
    next_before = items[-1].created_at if len(rows) > limit else None
    return ActivityPage(items=items, next_before=next_before)
