"""Workspaces, members, invitations. Role requirements are visible in each signature."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import DB, AdminCtx, Current, OwnerCtx, ViewerCtx
from app.models import Role
from app.schemas.auth import TokenRequest
from app.schemas.workspace import (
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
    InvitationPreview,
    MemberOut,
    MemberUpdate,
    TransferOwnership,
    WorkspaceCreate,
    WorkspaceDelete,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services import workspace_service as svc

router = APIRouter(tags=["workspaces"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


# ---------------------------------------------------------------- workspaces


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(current: Current, db: DB) -> list[WorkspaceOut]:
    return await svc.list_for_user(db, current.user)


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreate, current: Current, db: DB) -> WorkspaceOut:
    return await svc.create(db, current.user, body.name)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(ctx: ViewerCtx, db: DB) -> WorkspaceOut:
    return await svc.get_out(db, ctx)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(body: WorkspaceUpdate, ctx: AdminCtx, db: DB) -> WorkspaceOut:
    if body.name is None:
        return await svc.get_out(db, ctx)
    return await svc.rename(db, ctx, body.name)


@router.delete("/workspaces/{workspace_id}", status_code=NO_CONTENT)
async def delete_workspace(body: WorkspaceDelete, ctx: OwnerCtx, db: DB) -> Response:
    await svc.delete(db, ctx, body.confirm_name)
    return Response(status_code=NO_CONTENT)


@router.post(
    "/workspaces/{workspace_id}/ai-consent",
    response_model=WorkspaceOut,
    summary="Acknowledge that documents are sent to a third-party AI provider",
)
async def ai_consent(ctx: AdminCtx, db: DB) -> WorkspaceOut:
    return await svc.grant_ai_consent(db, ctx)


@router.post("/workspaces/{workspace_id}/transfer-ownership", status_code=NO_CONTENT)
async def transfer_ownership(body: TransferOwnership, ctx: OwnerCtx, db: DB) -> Response:
    await svc.transfer_ownership(db, ctx, body.new_owner_id)
    return Response(status_code=NO_CONTENT)


# ---------------------------------------------------------------- members


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(ctx: ViewerCtx, db: DB) -> list[MemberOut]:
    return await svc.list_members(db, ctx)


@router.patch("/workspaces/{workspace_id}/members/{user_id}", response_model=MemberOut)
async def update_member(user_id: uuid.UUID, body: MemberUpdate, ctx: AdminCtx, db: DB) -> MemberOut:
    return await svc.update_member_role(db, ctx, user_id, Role(body.role))


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=NO_CONTENT,
    summary="Remove a member (admin) or leave the workspace (yourself)",
)
async def remove_member(user_id: uuid.UUID, ctx: ViewerCtx, db: DB) -> Response:
    await svc.remove_member(db, ctx, user_id)
    return Response(status_code=NO_CONTENT)


# ---------------------------------------------------------------- invitations


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(body: InvitationCreate, ctx: AdminCtx, db: DB) -> InvitationCreated:
    return await svc.create_invitation(db, ctx, Role(body.role), body.email)


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(ctx: AdminCtx, db: DB) -> list[InvitationOut]:
    return await svc.list_invitations(db, ctx)


@router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}", status_code=NO_CONTENT)
async def revoke_invitation(invitation_id: uuid.UUID, ctx: AdminCtx, db: DB) -> Response:
    await svc.revoke_invitation(db, ctx, invitation_id)
    return Response(status_code=NO_CONTENT)


# Tokens travel in the body (not the URL) so they never appear in access logs.
@router.post("/invitations/preview", response_model=InvitationPreview)
async def preview_invitation(body: TokenRequest, current: Current, db: DB) -> InvitationPreview:
    return await svc.preview_invitation(db, body.token, current.user)


@router.post("/invitations/accept", response_model=WorkspaceOut)
async def accept_invitation(body: TokenRequest, current: Current, db: DB) -> WorkspaceOut:
    workspace_id = await svc.accept_invitation(db, body.token, current.user)
    return next(w for w in await svc.list_for_user(db, current.user) if w.id == workspace_id)
