"""Import every model so Base.metadata is complete (Alembic autogenerate, test truncation)."""

from app.models.base import Base
from app.models.chat import Conversation, Message, MessageCitation
from app.models.document import (
    Collection,
    CollectionDocument,
    Document,
    DocumentChunk,
    DocumentPage,
)
from app.models.ops import ActivityLog, AIUsageRecord, Notification, ProcessingJob
from app.models.user import AuthSession, AuthToken, RefreshToken, User
from app.models.workspace import Role, Workspace, WorkspaceInvitation, WorkspaceMember

__all__ = [
    "AIUsageRecord",
    "ActivityLog",
    "AuthSession",
    "AuthToken",
    "Base",
    "Collection",
    "CollectionDocument",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentPage",
    "Message",
    "MessageCitation",
    "Notification",
    "ProcessingJob",
    "RefreshToken",
    "Role",
    "User",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMember",
]
