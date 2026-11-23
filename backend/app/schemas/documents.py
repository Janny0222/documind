import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
FileType = Literal["pdf", "docx", "txt"]
DocumentStatus = Literal["uploaded", "queued", "processing", "ready", "failed", "deleting"]
SortOrder = Literal["newest", "oldest", "name", "size"]


class Uploader(BaseModel):
    id: uuid.UUID
    display_name: str


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    original_filename: str
    file_type: FileType
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    error_code: str | None
    error_message: str | None
    page_count: int | None
    page_unit: Literal["page", "section"]
    chunk_count: int | None
    collection_ids: list[uuid.UUID]
    uploaded_by: Uploader | None
    can_edit: bool = Field(description="Whether the current user may rename/delete it")
    created_at: datetime
    indexed_at: datetime | None


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    counts: dict[str, int] = Field(description="Documents per file type, ignoring the type filter")


class UploadResult(BaseModel):
    filename: str
    outcome: Literal["created", "duplicate", "rejected"]
    document: DocumentOut | None = None
    code: str | None = None
    detail: str | None = None


class DocumentUpdate(BaseModel):
    title: Title


class PageOut(BaseModel):
    page_number: int
    page_count: int
    page_unit: Literal["page", "section"]
    text: str


class DownloadOut(BaseModel):
    url: str
    expires_in: int


CollectionName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class CollectionCreate(BaseModel):
    name: CollectionName
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = (
        None
    )


class CollectionUpdate(BaseModel):
    name: CollectionName | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = (
        None
    )


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    document_count: int
    created_at: datetime
    updated_at: datetime


class CollectionDocumentsChange(BaseModel):
    document_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=100)]
