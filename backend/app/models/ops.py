"""Operational tables: job queue, AI usage ledger, notifications, activity log."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk


class ProcessingJob(UUIDPk, Timestamps, Base):
    """Postgres-backed job queue (claimed with FOR UPDATE SKIP LOCKED). See Phase 1 §C."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('index_document','purge_document','purge_workspace')", name="kind"
        ),
        CheckConstraint(
            "status IN ('queued','running','retry','succeeded','failed')", name="status"
        ),
        Index(
            "ix_processing_jobs_runnable",
            "run_after",
            postgresql_where=text("status IN ('queued','retry')"),
        ),
        # No duplicate in-flight jobs for the same document => no double indexing.
        Index(
            "uq_processing_jobs_inflight",
            "document_id",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('queued','running','retry')"),
        ),
    )

    # Nullable + SET NULL so purge jobs survive deleting the rows they clean up.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), server_default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIUsageRecord(UUIDPk, CreatedAt, Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('chat','embed_document','embed_query','rewrite_query')", name="operation"
        ),
        CheckConstraint("status IN ('ok','error','rate_limited','quota_exhausted')", name="status"),
        Index("ix_ai_usage_ws_created", "workspace_id", "created_at"),
        Index("ix_ai_usage_user_created", "user_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    operation: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    # Estimate from configured list prices - NOT provider billing data.
    est_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class Notification(UUIDPk, CreatedAt, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_user_unread",
            "user_id",
            "created_at",
            postgresql_where=text("read_at IS NULL"),
        ),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityLog(UUIDPk, CreatedAt, Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_logs_ws_created", "workspace_id", text("created_at DESC")),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
