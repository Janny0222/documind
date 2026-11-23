"""Schemas for Phase 6: semantic search, analytics, notifications, activity."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.chat import Scope, WorkspaceScope

# ---------------------------------------------------------------- search


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
    scope: Scope = WorkspaceScope()
    limit: Annotated[int, Field(ge=1, le=20)] = 10


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    file_type: Literal["pdf", "docx", "txt"]
    page_number: int | None
    page_unit: Literal["page", "section"]
    char_start: int
    char_end: int
    text: str
    score: float
    similarity: float | None
    keyword_match: bool


class SearchResponse(BaseModel):
    query: str
    mode: Literal["hybrid", "keyword"] = Field(
        description="hybrid = meaning + keywords; keyword = AI processing not allowed or unavailable"
    )
    hits: list[SearchHit]


# ---------------------------------------------------------------- analytics


class UsageTotals(BaseModel):
    questions: int
    answered: int
    not_found: int
    failed: int
    rate_limited: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float = Field(
        description="Estimate from configured list prices - not billing data"
    )


class DailyUsage(BaseModel):
    date: date
    questions: int
    input_tokens: int
    output_tokens: int


class OperationUsage(BaseModel):
    operation: str
    calls: int
    input_tokens: int
    output_tokens: int
    errors: int


class DocumentStats(BaseModel):
    total: int
    ready: int
    processing: int
    failed: int
    storage_bytes: int
    by_type: dict[str, int]
    uploads_in_range: int


class MemberUsage(BaseModel):
    user_id: uuid.UUID | None
    display_name: str
    questions: int


class UsageError(BaseModel):
    created_at: datetime
    operation: str
    status: str
    model: str


class Analytics(BaseModel):
    days: int
    since: date
    totals: UsageTotals
    daily: list[DailyUsage]
    by_operation: list[OperationUsage]
    documents: DocumentStats
    top_members: list[MemberUsage]
    recent_errors: list[UsageError]
    limits: dict[str, int]


# ---------------------------------------------------------------- notifications & activity


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    body: str
    link: str | None
    invitation_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None
    read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


class MarkRead(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, description="Omit to mark all as read")


class ActivityItem(BaseModel):
    id: uuid.UUID
    action: str
    actor: str | None
    target_type: str | None
    target_id: uuid.UUID | None
    meta: dict[str, object]
    created_at: datetime


class ActivityPage(BaseModel):
    items: list[ActivityItem]
    next_before: datetime | None
