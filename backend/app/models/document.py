"""Documents, pages, chunks and collections.

Tables are created in Phase 2 so the schema is reviewed as a whole; the endpoints that use
them arrive in Phases 4-5.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk

# Fixed by the chosen embedding model (gemini-embedding-001 truncated to 768 dims).
# Changing models means a new column + re-embed, never mixing vectors (see Phase 1 doc §D).
EMBEDDING_DIM = 768

DOCUMENT_STATUSES = ("uploaded", "queued", "processing", "ready", "failed", "deleting")


class Document(UUIDPk, Timestamps, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_documents_workspace_id_id"),
        CheckConstraint(
            "status IN ('uploaded','queued','processing','ready','failed','deleting')",
            name="status",
        ),
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("page_unit IN ('page','section')", name="page_unit"),
        Index(
            "ix_documents_workspace_status_created",
            "workspace_id",
            "status",
            text("created_at DESC"),
        ),
        # Same file uploaded twice into one workspace -> reuse instead of re-indexing.
        Index(
            "uq_documents_workspace_sha256_live",
            "workspace_id",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="uploaded", server_default="uploaded")
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer)
    # "page" for PDFs (real pages); "section" for DOCX/TXT, which have no stable pages.
    page_unit: Mapped[str] = mapped_column(String(10), default="page", server_default="page")
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPage(Base):
    """Normalized text per page (PDF) or synthetic section (DOCX/TXT) for previews."""

    __tablename__ = "document_pages"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)


class DocumentChunk(UUIDPk, CreatedAt, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        # workspace_id is denormalized so vector search filters tenants inside SQL.
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            ondelete="CASCADE",
            name="fk_document_chunks_workspace_document",
        ),
        Index("ix_document_chunks_workspace_document", "workspace_id", "document_id"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column()
    document_id: Mapped[uuid.UUID] = mapped_column()
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english'::regconfig, content)", persisted=True)
    )


class Collection(UUIDPk, Timestamps, Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_collections_workspace_id_id"),
        UniqueConstraint("workspace_id", "name", name="uq_collections_workspace_name"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class CollectionDocument(Base):
    """Many-to-many. Composite FKs make it impossible to link a collection to a document
    from a different workspace, even through a bug in application code."""

    __tablename__ = "collection_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "collection_id"],
            ["collections.workspace_id", "collections.id"],
            ondelete="CASCADE",
            name="fk_collection_documents_collection",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            ondelete="CASCADE",
            name="fk_collection_documents_document",
        ),
        Index("ix_collection_documents_document", "document_id"),
    )

    collection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column()
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
