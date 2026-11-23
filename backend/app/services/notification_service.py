"""In-app notifications (Phase 1: "Notifications should initially be in-app").

A notification belongs to one user. Payload carries display text and an in-app link, so the
frontend renders it without extra lookups. Notifications are only ever listed for their owner.
"""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.schemas.insights import NotificationList, NotificationOut
from app.services.auth_service import utcnow

KINDS = ("document_ready", "document_failed", "invitation", "member_joined")


def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Adds a notification to the caller's transaction (it commits with the event it describes)."""
    assert kind in KINDS, kind
    db.add(
        Notification(
            user_id=user_id,
            workspace_id=workspace_id,
            type=kind,
            payload={"title": title[:200], "body": body[:500], "link": link, **(extra or {})},
        )
    )


def _out(n: Notification) -> NotificationOut:
    p = n.payload or {}
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=str(p.get("title", "")),
        body=str(p.get("body", "")),
        link=p.get("link"),
        invitation_id=p.get("invitation_id"),
        workspace_id=n.workspace_id,
        read=n.read_at is not None,
        created_at=n.created_at,
    )


async def list_for_user(
    db: AsyncSession, user_id: uuid.UUID, *, unread_only: bool, limit: int
) -> NotificationList:
    q = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    items = (
        (await db.execute(q.order_by(Notification.created_at.desc()).limit(limit))).scalars().all()
    )
    unread = (
        await db.execute(
            select(func.count()).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
    ).scalar_one()
    return NotificationList(items=[_out(n) for n in items], unread=unread)


async def mark_read(db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID] | None) -> int:
    """Marks the given ids (or all, when ids is None) as read. Other users' ids are ignored."""
    stmt = update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    result = await db.execute(stmt.values(read_at=utcnow()))
    await db.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
