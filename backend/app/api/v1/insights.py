"""Phase 6 endpoints: semantic search, analytics, activity, notifications."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DB, AdminCtx, Current, ViewerCtx
from app.core.rate_limit import enforce
from app.schemas.insights import (
    ActivityPage,
    Analytics,
    MarkRead,
    NotificationList,
    SearchRequest,
    SearchResponse,
)
from app.schemas.workspace import WorkspaceOut
from app.services import analytics_service, notification_service, search_service, workspace_service
from app.services.activity_feed import list_activity

router = APIRouter()
WS = "/workspaces/{workspace_id}"


@router.post(
    f"{WS}/search",
    response_model=SearchResponse,
    tags=["search"],
    summary="Find passages by meaning and keywords (no AI answer, no question quota used)",
)
async def search(body: SearchRequest, ctx: ViewerCtx, db: DB) -> SearchResponse:
    enforce(f"search:user:{ctx.user.id}", 30, 60)
    return await search_service.search(
        db, ctx, body.query, body.scope.model_dump(mode="json"), body.limit
    )


@router.get(
    f"{WS}/analytics",
    response_model=Analytics,
    tags=["analytics"],
    summary="Usage and document statistics (admins). Costs are estimates, not billing data.",
)
async def analytics(
    ctx: AdminCtx, db: DB, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> Analytics:
    return await analytics_service.workspace_analytics(db, ctx, days)


@router.get(f"{WS}/activity", response_model=ActivityPage, tags=["analytics"])
async def activity(
    ctx: AdminCtx,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: datetime | None = None,
) -> ActivityPage:
    return await list_activity(db, ctx, limit=limit, before=before)


@router.get("/notifications", response_model=NotificationList, tags=["notifications"])
async def notifications(
    current: Current,
    db: DB,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NotificationList:
    return await notification_service.list_for_user(
        db, current.user.id, unread_only=unread_only, limit=limit
    )


@router.post("/notifications/read", response_model=dict[str, int], tags=["notifications"])
async def mark_read(body: MarkRead, current: Current, db: DB) -> dict[str, int]:
    return {"updated": await notification_service.mark_read(db, current.user.id, body.ids)}


@router.post(
    "/invitations/{invitation_id}/accept",
    response_model=WorkspaceOut,
    tags=["workspaces"],
    summary="Accept an invitation addressed to your email (from a notification)",
)
async def accept_by_id(invitation_id: uuid.UUID, current: Current, db: DB) -> WorkspaceOut:
    workspace_id = await workspace_service.accept_invitation_by_id(db, invitation_id, current.user)
    return next(
        w for w in await workspace_service.list_for_user(db, current.user) if w.id == workspace_id
    )
