import uuid
from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk


class Conversation(UUIDPk, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_ws_user_updated", "workspace_id", "user_id", text("updated_at DESC")
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    # {"type": "workspace"} | {"type": "collection", "id": ...} | {"type": "documents", "ids": [...]}
    scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text('\'{"type": "workspace"}\'::jsonb')
    )


class Message(UUIDPk, CreatedAt, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="role"),
        CheckConstraint("status IN ('complete','streaming','failed','not_found')", name="status"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="complete")
    regenerated_from: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    model: Mapped[str | None] = mapped_column(String(100))


class MessageCitation(UUIDPk, Base):
    """Snapshot of the evidence behind an answer. chunk/document FKs go NULL when the source
    is deleted, but document_title/page/excerpt remain so the answer still reads correctly."""

    __tablename__ = "message_citations"
    __table_args__ = (Index("ix_message_citations_message", "message_id"),)

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    marker: Mapped[str] = mapped_column(String(8))  # e.g. "S1"
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_title: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
