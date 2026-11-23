"""Workspaces, members and invitations.

Every function receives an already-authorized WorkspaceContext (built by the
`require_workspace` dependency), so it never trusts a workspace id from the client alone.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import ScalarSelect, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.security import hash_token, new_opaque_token
from app.models import Document, Role, User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.schemas.workspace import (
    InvitationCreated,
    InvitationOut,
    InvitationPreview,
    MemberOut,
    WorkspaceOut,
)
from app.services.activity import record_activity
from app.services.auth_service import utcnow
from app.services.email import send_email
from app.services.notification_service import notify
from app.workers.queue import enqueue
from app.workers.runner import nudge_runner

MAX_PENDING_INVITATIONS = 50


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    user: User
    role: Role

    @property
    def id(self) -> uuid.UUID:
        return self.workspace.id


# ---------------------------------------------------------------- workspaces


def _member_count_subq() -> ScalarSelect[int]:
    return (
        select(func.count())
        .where(WorkspaceMember.workspace_id == Workspace.id)
        .correlate(Workspace)
        .scalar_subquery()
    )


def _to_out(ws: Workspace, role: str, member_count: int) -> WorkspaceOut:
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        role=Role(role),
        is_personal=ws.is_personal,
        is_demo=ws.is_demo,
        ai_consent=ws.ai_consent_at is not None,
        member_count=member_count,
        created_at=ws.created_at,
    )


async def list_for_user(db: AsyncSession, user: User) -> list[WorkspaceOut]:
    rows = (
        await db.execute(
            select(Workspace, WorkspaceMember.role, _member_count_subq())
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.is_personal.desc(), Workspace.created_at)
        )
    ).all()
    return [_to_out(ws, role, count) for ws, role, count in rows]


async def get_out(db: AsyncSession, ctx: WorkspaceContext) -> WorkspaceOut:
    count = (
        await db.execute(select(func.count()).where(WorkspaceMember.workspace_id == ctx.id))
    ).scalar_one()
    return _to_out(ctx.workspace, ctx.role, count)


async def create(db: AsyncSession, user: User, name: str) -> WorkspaceOut:
    owned = (
        await db.execute(
            select(func.count()).where(
                WorkspaceMember.user_id == user.id, WorkspaceMember.role == Role.OWNER
            )
        )
    ).scalar_one()
    if owned >= get_settings().max_owned_workspaces:
        raise Conflict("You have reached the maximum number of workspaces", code="workspace_limit")

    ws = Workspace(name=name)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.OWNER))
    record_activity(
        db,
        workspace_id=ws.id,
        actor_id=user.id,
        action="workspace.created",
        target_type="workspace",
        target_id=ws.id,
    )
    await db.commit()
    await db.refresh(ws)
    return _to_out(ws, Role.OWNER, 1)


async def rename(db: AsyncSession, ctx: WorkspaceContext, name: str) -> WorkspaceOut:
    old = ctx.workspace.name
    ctx.workspace.name = name
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="workspace.renamed",
        target_type="workspace",
        target_id=ctx.id,
        meta={"from": old, "to": name},
    )
    await db.commit()
    await db.refresh(ctx.workspace)
    return await get_out(db, ctx)


async def delete(db: AsyncSession, ctx: WorkspaceContext, confirm_name: str) -> None:
    if ctx.workspace.is_personal:
        raise Conflict("Your personal workspace cannot be deleted", code="personal_workspace")
    if confirm_name != ctx.workspace.name:
        raise ValidationFailed(
            "Type the workspace name exactly to confirm", code="confirmation_mismatch"
        )
    # FK cascades remove members, documents, chunks, conversations, usage, activity.
    # The stored files go in a background job (the job row survives: its FK is SET NULL).
    enqueue(db, kind="purge_workspace", workspace_id=None, payload={"prefix": f"ws/{ctx.id}/"})
    await db.delete(ctx.workspace)
    await db.commit()
    nudge_runner()


async def grant_ai_consent(db: AsyncSession, ctx: WorkspaceContext) -> WorkspaceOut:
    if ctx.workspace.ai_consent_at is None:
        ctx.workspace.ai_consent_at = utcnow()
        ctx.workspace.ai_consent_by = ctx.user.id
        record_activity(
            db,
            workspace_id=ctx.id,
            actor_id=ctx.user.id,
            action="workspace.ai_consent_granted",
            target_type="workspace",
            target_id=ctx.id,
        )
        # Documents indexed before consent have no embeddings yet: re-index them (idempotent).
        pending = (
            await db.execute(
                select(Document).where(
                    Document.workspace_id == ctx.id,
                    Document.deleted_at.is_(None),
                    Document.status == "ready",
                    Document.embedding_model.is_(None),
                )
            )
        ).scalars()
        queued = 0
        for doc in pending:
            doc.status = "queued"
            enqueue(db, kind="index_document", workspace_id=ctx.id, document_id=doc.id)
            queued += 1
        await db.commit()
        await db.refresh(ctx.workspace)
        if queued:
            nudge_runner()
    return await get_out(db, ctx)


async def transfer_ownership(
    db: AsyncSession, ctx: WorkspaceContext, new_owner_id: uuid.UUID
) -> None:
    if new_owner_id == ctx.user.id:
        raise Conflict("You already own this workspace", code="already_owner")
    target = await _get_member(db, ctx.id, new_owner_id)
    current = await _get_member(db, ctx.id, ctx.user.id)
    # Demote first and flush: the partial unique index allows only one owner at a time.
    current.role = Role.ADMIN
    await db.flush()
    target.role = Role.OWNER
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="workspace.ownership_transferred",
        target_type="user",
        target_id=new_owner_id,
    )
    await db.commit()


# ---------------------------------------------------------------- members


async def _get_member(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember:
    member = await db.get(WorkspaceMember, (workspace_id, user_id))
    if member is None:
        raise NotFound("Member not found")
    return member


async def list_members(db: AsyncSession, ctx: WorkspaceContext) -> list[MemberOut]:
    query = (
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ctx.id)
        .order_by(WorkspaceMember.joined_at)
    )
    if ctx.workspace.is_demo:
        # Strangers share the demo: never show them each other's names or emails.
        query = query.where(WorkspaceMember.user_id == ctx.user.id)
    rows = (await db.execute(query)).all()
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=Role(m.role),
            joined_at=m.joined_at,
        )
        for m, u in rows
    ]


def _assert_can_manage(ctx: WorkspaceContext, target_role: Role) -> None:
    """Owners manage everyone but themselves; admins manage only members and viewers."""
    if target_role == Role.OWNER:
        raise Forbidden(
            "The owner's role can only change through ownership transfer", code="owner_protected"
        )
    if ctx.role == Role.ADMIN and target_role == Role.ADMIN:
        raise Forbidden("Admins cannot manage other admins", code="insufficient_role")


async def update_member_role(
    db: AsyncSession, ctx: WorkspaceContext, user_id: uuid.UUID, new_role: Role
) -> MemberOut:
    if user_id == ctx.user.id:
        raise Forbidden("You cannot change your own role", code="self_role_change")
    member = await _get_member(db, ctx.id, user_id)
    _assert_can_manage(ctx, Role(member.role))
    if new_role == Role.ADMIN and ctx.role != Role.OWNER:
        raise Forbidden("Only the owner can grant the admin role", code="insufficient_role")

    old = member.role
    member.role = new_role
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="member.role_changed",
        target_type="user",
        target_id=user_id,
        meta={"from": old, "to": new_role.value},
    )
    await db.commit()
    user = await db.get(User, user_id)
    assert user is not None
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=new_role,
        joined_at=member.joined_at,
    )


async def remove_member(db: AsyncSession, ctx: WorkspaceContext, user_id: uuid.UUID) -> None:
    member = await _get_member(db, ctx.id, user_id)
    if user_id == ctx.user.id:
        if ctx.role == Role.OWNER:
            raise Conflict(
                "Transfer ownership before leaving the workspace", code="owner_cannot_leave"
            )
        action = "member.left"
    else:
        if not ctx.role.at_least(Role.ADMIN):
            raise Forbidden(
                "You do not have permission to remove members", code="insufficient_role"
            )
        _assert_can_manage(ctx, Role(member.role))
        action = "member.removed"
    await db.delete(member)
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action=action,
        target_type="user",
        target_id=user_id,
    )
    await db.commit()


# ---------------------------------------------------------------- invitations


def _invitation_out(inv: WorkspaceInvitation) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role=Role(inv.role),
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    )


async def create_invitation(
    db: AsyncSession, ctx: WorkspaceContext, role: Role, email: str | None
) -> InvitationCreated:
    if role == Role.ADMIN and ctx.role != Role.OWNER:
        raise Forbidden("Only the owner can invite admins", code="insufficient_role")
    if ctx.workspace.is_demo:
        raise Forbidden("Invitations are disabled for this workspace", code="invitations_disabled")

    pending = (
        await db.execute(
            select(func.count()).where(
                WorkspaceInvitation.workspace_id == ctx.id,
                WorkspaceInvitation.accepted_at.is_(None),
                WorkspaceInvitation.revoked_at.is_(None),
                WorkspaceInvitation.expires_at > utcnow(),
            )
        )
    ).scalar_one()
    if pending >= MAX_PENDING_INVITATIONS:
        raise Conflict("Too many pending invitations", code="invitation_limit")

    if email:
        already = (
            await db.execute(
                select(WorkspaceMember.user_id)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(WorkspaceMember.workspace_id == ctx.id, User.email == email)
            )
        ).first()
        if already:
            raise Conflict("That person is already a member", code="already_member")

    s = get_settings()
    raw = new_opaque_token()
    inv = WorkspaceInvitation(
        workspace_id=ctx.id,
        email=email,
        role=role,
        token_hash=hash_token(raw),
        invited_by=ctx.user.id,
        expires_at=utcnow() + timedelta(days=s.invitation_ttl_days),
    )
    db.add(inv)
    if email:
        await db.flush()  # need inv.id for the notification
        invitee = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if invitee is not None:
            # No token in the notification (tokens are stored hashed); the invitee accepts by id,
            # which only works for the user whose email the invitation names.
            notify(
                db,
                user_id=invitee.id,
                workspace_id=ctx.id,
                kind="invitation",
                title=f"{ctx.user.display_name} invited you to {ctx.workspace.name}",
                body=f"Join as {role.value}.",
                extra={"invitation_id": str(inv.id)},
            )
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="invitation.created",
        target_type="invitation",
        meta={"role": role.value, "email": email},
    )
    await db.commit()
    await db.refresh(inv)

    url = f"{s.frontend_url}/invite#token={raw}"
    if email:
        await send_email(
            email,
            f"You're invited to {ctx.workspace.name} on DocuMind",
            f"{ctx.user.display_name} invited you to join. Accept: {url}",
        )
    return InvitationCreated(**_invitation_out(inv).model_dump(), token=raw, invite_url=url)


async def list_invitations(db: AsyncSession, ctx: WorkspaceContext) -> list[InvitationOut]:
    rows = (
        await db.execute(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.workspace_id == ctx.id,
                WorkspaceInvitation.accepted_at.is_(None),
                WorkspaceInvitation.revoked_at.is_(None),
                WorkspaceInvitation.expires_at > utcnow(),
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        )
    ).scalars()
    return [_invitation_out(i) for i in rows]


async def revoke_invitation(
    db: AsyncSession, ctx: WorkspaceContext, invitation_id: uuid.UUID
) -> None:
    inv = (
        await db.execute(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.id == invitation_id, WorkspaceInvitation.workspace_id == ctx.id
            )
        )
    ).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.revoked_at is not None:
        raise NotFound("Invitation not found")
    inv.revoked_at = utcnow()
    await db.commit()


async def _usable_invitation(
    db: AsyncSession, raw: str, user: User, *, lock: bool = False
) -> tuple[WorkspaceInvitation, Workspace]:
    stmt = (
        select(WorkspaceInvitation, Workspace)
        .join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
        .where(WorkspaceInvitation.token_hash == hash_token(raw))
    )
    if lock:
        stmt = stmt.with_for_update(of=WorkspaceInvitation)
    row = (await db.execute(stmt)).first()
    if row is None:
        raise NotFound("This invitation is invalid or has expired", code="invalid_invitation")
    inv, ws = row
    _assert_usable(inv, user)
    return inv, ws


def _assert_usable(inv: WorkspaceInvitation, user: User, *, require_email: bool = False) -> None:
    if (
        inv.accepted_at is not None
        or inv.revoked_at is not None
        or inv.expires_at <= utcnow()
        or (require_email and inv.email is None)
        or (inv.email is not None and inv.email.lower() != user.email.lower())
    ):
        raise NotFound("This invitation is invalid or has expired", code="invalid_invitation")


async def preview_invitation(db: AsyncSession, raw: str, user: User) -> InvitationPreview:
    inv, ws = await _usable_invitation(db, raw, user)
    inviter = await db.get(User, inv.invited_by) if inv.invited_by else None
    return InvitationPreview(
        workspace_id=ws.id,
        workspace_name=ws.name,
        role=Role(inv.role),
        invited_by=inviter.display_name if inviter else None,
        expires_at=inv.expires_at,
    )


async def accept_invitation(db: AsyncSession, raw: str, user: User) -> uuid.UUID:
    inv, ws = await _usable_invitation(db, raw, user, lock=True)
    return await _join(db, inv, ws, user)


async def accept_invitation_by_id(
    db: AsyncSession, invitation_id: uuid.UUID, user: User
) -> uuid.UUID:
    """Accept from an in-app notification. Only email-addressed invitations, and only by the
    signed-in user with that exact email - anyone else gets the same 404."""
    row = (
        await db.execute(
            select(WorkspaceInvitation, Workspace)
            .join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
            .where(WorkspaceInvitation.id == invitation_id)
            .with_for_update(of=WorkspaceInvitation)
        )
    ).first()
    if row is None:
        raise NotFound("This invitation is invalid or has expired", code="invalid_invitation")
    inv, ws = row
    _assert_usable(inv, user, require_email=True)
    return await _join(db, inv, ws, user)


async def _join(db: AsyncSession, inv: WorkspaceInvitation, ws: Workspace, user: User) -> uuid.UUID:
    if await db.get(WorkspaceMember, (ws.id, user.id)):
        raise Conflict("You are already a member of this workspace", code="already_member")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=inv.role))
    inv.accepted_at = utcnow()
    inv.accepted_by = user.id
    record_activity(
        db,
        workspace_id=ws.id,
        actor_id=user.id,
        action="member.joined",
        target_type="user",
        target_id=user.id,
        meta={"role": inv.role},
    )
    if inv.invited_by and inv.invited_by != user.id:
        notify(
            db,
            user_id=inv.invited_by,
            workspace_id=ws.id,
            kind="member_joined",
            title=f"{user.display_name} joined {ws.name}",
            body=f"As {inv.role}.",
            link=f"/w/{ws.id}/settings/members",
        )
    await db.commit()
    return ws.id
