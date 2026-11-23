"""Request dependencies - the authentication and authorization choke points.

Every workspace-scoped route depends on `require_workspace(min_role)`. It resolves the
membership from the authenticated user + workspace id in the path. A non-member gets 404
(not 403), so workspace ids can't be probed for existence.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import ACCESS_COOKIE
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Role, Workspace, WorkspaceMember
from app.services.auth_service import CurrentUser, resolve_access
from app.services.workspace_service import WorkspaceContext

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, db: DB) -> CurrentUser:
    token = request.cookies.get(ACCESS_COOKIE)
    claims = decode_access_token(token) if token else None
    if claims is None:
        raise Unauthorized("Authentication required", code="not_authenticated")
    current = await resolve_access(db, claims.user_id, claims.session_id)
    if current is None:
        raise Unauthorized("Session expired", code="session_expired")
    return current


Current = Annotated[CurrentUser, Depends(get_current_user)]


def require_workspace(min_role: Role = Role.VIEWER) -> Callable[..., Awaitable[WorkspaceContext]]:
    async def _dependency(workspace_id: uuid.UUID, current: Current, db: DB) -> WorkspaceContext:
        row = (
            await db.execute(
                select(Workspace, WorkspaceMember.role)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(Workspace.id == workspace_id, WorkspaceMember.user_id == current.user.id)
            )
        ).first()
        if row is None:
            raise NotFound("Workspace not found")
        workspace, role = row
        ctx = WorkspaceContext(workspace=workspace, user=current.user, role=Role(role))
        if not ctx.role.at_least(min_role):
            raise Forbidden("Your role does not allow this action", code="insufficient_role")
        return ctx

    return _dependency


ViewerCtx = Annotated[WorkspaceContext, Depends(require_workspace(Role.VIEWER))]
MemberCtx = Annotated[WorkspaceContext, Depends(require_workspace(Role.MEMBER))]
AdminCtx = Annotated[WorkspaceContext, Depends(require_workspace(Role.ADMIN))]
OwnerCtx = Annotated[WorkspaceContext, Depends(require_workspace(Role.OWNER))]
