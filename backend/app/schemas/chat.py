import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


class WorkspaceScope(BaseModel):
    type: Literal["workspace"] = "workspace"


class CollectionScope(BaseModel):
    type: Literal["collection"]
    id: uuid.UUID


class DocumentsScope(BaseModel):
    type: Literal["documents"]
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=20)]


Scope = Annotated[WorkspaceScope | CollectionScope | DocumentsScope, Field(discriminator="type")]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ConversationCreate(BaseModel):
    scope: Scope = WorkspaceScope()
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None


class ConversationUpdate(BaseModel):
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    scope: Scope | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    scope: Scope
    created_at: datetime
    updated_at: datetime


class CitationOut(BaseModel):
    marker: str
    document_id: uuid.UUID | None = Field(description="null when the source document was deleted")
    document_title: str
    page_number: int | None
    page_unit: Literal["page", "section"]
    excerpt: str
    chunk_id: uuid.UUID | None
    char_start: int | None = None
    char_end: int | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["complete", "streaming", "failed", "not_found"]
    created_at: datetime
    citations: list[CitationOut] = []


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class AskRequest(BaseModel):
    content: Question


class AiStatus(BaseModel):
    configured: bool
    consent: bool
    questions_left_today: int
    daily_limit: int
    chat_model: str
