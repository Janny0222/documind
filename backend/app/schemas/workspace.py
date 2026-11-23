import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, StringConstraints

from app.models.workspace import Role

WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
AssignableRole = Literal["admin", "member", "viewer"]


class WorkspaceCreate(BaseModel):
    name: WorkspaceName


class WorkspaceUpdate(BaseModel):
    name: WorkspaceName | None = None


class WorkspaceDelete(BaseModel):
    confirm_name: str  # must equal the workspace name - guards against accidental deletion


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    is_personal: bool
    is_demo: bool
    ai_consent: bool
    member_count: int
    created_at: datetime


class TransferOwnership(BaseModel):
    new_owner_id: uuid.UUID


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    display_name: str
    role: Role
    joined_at: datetime


class MemberUpdate(BaseModel):
    role: AssignableRole


class InvitationCreate(BaseModel):
    role: AssignableRole = "member"
    email: EmailStr | None = None


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: EmailStr | None
    role: Role
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationOut):
    token: str  # returned exactly once; only its hash is stored
    invite_url: str


class InvitationPreview(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    role: Role
    invited_by: str | None
    expires_at: datetime
