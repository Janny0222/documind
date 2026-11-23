"""Documents: upload, list, rename, delete, reprocess, preview, download.

Every query is scoped by the authorized workspace (WorkspaceContext) - a document id from another
workspace simply isn't found.
"""

import asyncio
import hashlib
import re
import tempfile
import unicodedata
import uuid
from collections.abc import Sequence
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound
from app.integrations.storage import LocalStorage, document_key, get_storage
from app.models import (
    CollectionDocument,
    Document,
    DocumentChunk,
    DocumentPage,
    Role,
    User,
)
from app.rag.validation import MIME, FileKind, ValidationError, kind_from_filename, validate_file
from app.schemas.documents import DocumentList, DocumentOut, PageOut, Uploader, UploadResult
from app.services.activity import record_activity
from app.services.auth_service import utcnow
from app.services.workspace_service import WorkspaceContext
from app.workers.queue import enqueue

LIVE = Document.deleted_at.is_(None)
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")
TYPE_BY_MIME = {mime: kind.value for kind, mime in MIME.items()}


# ------------------------------------------------------------------ helpers


def sanitize_filename(name: str | None) -> str:
    """Display-only name: no paths, no control characters, bounded length. Never used as a key."""
    name = unicodedata.normalize("NFC", (name or "").replace("\\", "/").rsplit("/", 1)[-1])
    name = _UNSAFE_NAME.sub("", name).strip().strip(".") or "document"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 200 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 10 else name[:200]
    return name


def can_edit(ctx: WorkspaceContext, doc: Document) -> bool:
    if ctx.role.at_least(Role.ADMIN):
        return True
    return ctx.role == Role.MEMBER and doc.uploaded_by == ctx.user.id


async def _collection_ids(
    db: AsyncSession, doc_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not doc_ids:
        return {}
    rows = await db.execute(
        select(CollectionDocument.document_id, CollectionDocument.collection_id).where(
            CollectionDocument.document_id.in_(doc_ids)
        )
    )
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for doc_id, col_id in rows:
        out.setdefault(doc_id, []).append(col_id)
    return out


async def to_out(
    db: AsyncSession, ctx: WorkspaceContext, docs: Sequence[Document]
) -> list[DocumentOut]:
    ids = [d.id for d in docs]
    collections = await _collection_ids(db, ids)
    uploader_ids = {d.uploaded_by for d in docs if d.uploaded_by}
    uploaders = {}
    if uploader_ids:
        uploaders = {
            u.id: u
            for u in (await db.execute(select(User).where(User.id.in_(uploader_ids)))).scalars()
        }
    out = []
    for d in docs:
        u = uploaders.get(d.uploaded_by) if d.uploaded_by else None
        out.append(
            DocumentOut(
                id=d.id,
                title=d.title,
                original_filename=d.original_filename,
                file_type=TYPE_BY_MIME.get(d.mime_type, "txt"),
                mime_type=d.mime_type,
                size_bytes=d.size_bytes,
                status=d.status,
                error_code=d.error_code,
                error_message=d.error_message,
                page_count=d.page_count,
                page_unit=d.page_unit,
                chunk_count=d.chunk_count,
                collection_ids=collections.get(d.id, []),
                uploaded_by=Uploader(id=u.id, display_name=u.display_name) if u else None,
                can_edit=can_edit(ctx, d),
                created_at=d.created_at,
                indexed_at=d.indexed_at,
            )
        )
    return out


async def get_document(db: AsyncSession, ctx: WorkspaceContext, document_id: uuid.UUID) -> Document:
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id, Document.workspace_id == ctx.id, LIVE
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFound("Document not found")
    return doc


# ------------------------------------------------------------------ upload


async def _spool(upload: UploadFile, dest: Path, max_bytes: int) -> tuple[int, str]:
    """Copies the upload to a temp file in 1 MB pieces, hashing as it goes and stopping
    as soon as the size limit is exceeded (never holds a whole file in memory)."""
    digest = hashlib.sha256()
    size = 0
    with dest.open("wb") as out:
        while piece := await upload.read(1024 * 1024):
            size += len(piece)
            if size > max_bytes:
                raise ValidationError(
                    "file_too_large", f"This file is larger than {max_bytes // (1024 * 1024)} MB."
                )
            digest.update(piece)
            out.write(piece)
    return size, digest.hexdigest()


async def upload_files(
    db: AsyncSession, ctx: WorkspaceContext, files: list[UploadFile]
) -> list[UploadResult]:
    s = get_settings()
    results: list[UploadResult] = []
    storage = get_storage()
    queued = False

    for upload in files[: s.max_files_per_upload]:
        filename = sanitize_filename(upload.filename)
        try:
            live_count = (
                await db.execute(select(func.count()).where(Document.workspace_id == ctx.id, LIVE))
            ).scalar_one()
            if live_count >= s.max_documents_per_workspace:
                raise ValidationError(
                    "document_limit",
                    f"This workspace has reached its limit of {s.max_documents_per_workspace} documents.",
                )
            kind = kind_from_filename(filename)
            with tempfile.TemporaryDirectory(prefix="documind-upload-") as tmp:
                path = Path(tmp) / f"upload.{kind.value}"
                size, sha256 = await _spool(upload, path, s.max_upload_bytes)
                kind = await asyncio.to_thread(validate_file, path, filename)

                duplicate = (
                    await db.execute(
                        select(Document).where(
                            Document.workspace_id == ctx.id, Document.sha256 == sha256, LIVE
                        )
                    )
                ).scalar_one_or_none()
                if duplicate is not None:
                    out = (await to_out(db, ctx, [duplicate]))[0]
                    results.append(
                        UploadResult(
                            filename=filename,
                            outcome="duplicate",
                            document=out,
                            detail="This file is already in the workspace.",
                        )
                    )
                    continue

                doc_id = uuid.uuid4()
                key = document_key(ctx.id, doc_id)
                await storage.put_file(key, path, MIME[kind])

            doc = Document(
                id=doc_id,
                workspace_id=ctx.id,
                uploaded_by=ctx.user.id,
                title=Path(filename).stem[:255] or filename,
                original_filename=filename,
                mime_type=MIME[kind],
                size_bytes=size,
                storage_key=key,
                sha256=sha256,
                status="queued",
                page_unit="page" if kind is FileKind.PDF else "section",
            )
            db.add(doc)
            enqueue(db, kind="index_document", workspace_id=ctx.id, document_id=doc_id)
            record_activity(
                db,
                workspace_id=ctx.id,
                actor_id=ctx.user.id,
                action="document.uploaded",
                target_type="document",
                target_id=doc_id,
                meta={"filename": filename, "bytes": size},
            )
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                await storage.delete(key)  # don't leave an orphaned object behind
                raise
            await db.refresh(doc)
            queued = True
            results.append(
                UploadResult(
                    filename=filename, outcome="created", document=(await to_out(db, ctx, [doc]))[0]
                )
            )
        except ValidationError as exc:
            results.append(
                UploadResult(
                    filename=filename, outcome="rejected", code=exc.code, detail=exc.message
                )
            )
        finally:
            await upload.close()

    for extra in files[s.max_files_per_upload :]:
        results.append(
            UploadResult(
                filename=sanitize_filename(extra.filename),
                outcome="rejected",
                code="too_many_files",
                detail=f"Upload at most {s.max_files_per_upload} files at a time.",
            )
        )
    if queued:
        from app.workers.runner import (
            nudge_runner,
        )  # local import: runner imports services indirectly

        nudge_runner()
    return results


# ------------------------------------------------------------------ list / read


async def list_documents(
    db: AsyncSession,
    ctx: WorkspaceContext,
    *,
    q: str | None,
    file_type: str | None,
    status: str | None,
    collection_id: uuid.UUID | None,
    sort: str,
    limit: int,
    offset: int,
) -> DocumentList:
    base = select(Document).where(Document.workspace_id == ctx.id, LIVE)
    if q:
        # Escape LIKE wildcards so searching for "50%" or "a_b" matches literally.
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        base = base.where(
            or_(
                Document.title.ilike(pattern, escape="\\"),
                Document.original_filename.ilike(pattern, escape="\\"),
            )
        )
    if status:
        base = base.where(Document.status == status)
    if collection_id:
        base = base.where(
            Document.id.in_(
                select(CollectionDocument.document_id).where(
                    CollectionDocument.collection_id == collection_id,
                    CollectionDocument.workspace_id == ctx.id,
                )
            )
        )

    # Counts per type ignore the type filter, so the filter pills can show totals.
    filtered = base.subquery()
    count_rows = await db.execute(
        select(filtered.c.mime_type, func.count()).group_by(filtered.c.mime_type)
    )
    counts = {"all": 0, "pdf": 0, "docx": 0, "txt": 0}
    for mime, n in count_rows:
        counts[TYPE_BY_MIME.get(mime, "txt")] += n
        counts["all"] += n

    if file_type:
        mime = MIME.get(FileKind(file_type))
        base = base.where(Document.mime_type == mime)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    order = {
        "newest": [Document.created_at.desc()],
        "oldest": [Document.created_at.asc()],
        "name": [func.lower(Document.title).asc()],
        "size": [Document.size_bytes.desc()],
    }[sort]
    docs = (
        (await db.execute(base.order_by(*order, Document.id).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return DocumentList(items=await to_out(db, ctx, docs), total=total, counts=counts)


async def get_page(
    db: AsyncSession, ctx: WorkspaceContext, document_id: uuid.UUID, page_number: int
) -> PageOut:
    doc = await get_document(db, ctx, document_id)
    if doc.status != "ready" or not doc.page_count:
        raise Conflict("This document isn't ready to preview yet", code="not_ready")
    page = await db.get(DocumentPage, (doc.id, page_number))
    if page is None:
        raise NotFound(f"{doc.page_unit.capitalize()} {page_number} doesn't exist")
    return PageOut(
        page_number=page_number, page_count=doc.page_count, page_unit=doc.page_unit, text=page.text
    )


# ------------------------------------------------------------------ modify


def _assert_can_edit(ctx: WorkspaceContext, doc: Document) -> None:
    if not can_edit(ctx, doc):
        raise Forbidden(
            "Only the uploader or an admin can change this document", code="insufficient_role"
        )


async def rename(
    db: AsyncSession, ctx: WorkspaceContext, document_id: uuid.UUID, title: str
) -> DocumentOut:
    doc = await get_document(db, ctx, document_id)
    _assert_can_edit(ctx, doc)
    doc.title = title
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="document.renamed",
        target_type="document",
        target_id=doc.id,
    )
    await db.commit()
    await db.refresh(doc)
    return (await to_out(db, ctx, [doc]))[0]


async def delete_document(db: AsyncSession, ctx: WorkspaceContext, document_id: uuid.UUID) -> None:
    """Step 1 (this transaction): hide the document and remove everything searchable - chunks,
    pages, collection links. Step 2 (purge job): delete the stored file, then the row."""
    doc = await get_document(db, ctx, document_id)
    _assert_can_edit(ctx, doc)
    doc.deleted_at = utcnow()
    doc.status = "deleting"
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    await db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
    await db.execute(delete(CollectionDocument).where(CollectionDocument.document_id == doc.id))
    enqueue(
        db,
        kind="purge_document",
        workspace_id=ctx.id,
        document_id=doc.id,
        payload={"storage_key": doc.storage_key},
    )
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="document.deleted",
        target_type="document",
        target_id=doc.id,
        meta={"title": doc.title},
    )
    await db.commit()
    from app.workers.runner import nudge_runner

    nudge_runner()


async def reprocess(db: AsyncSession, ctx: WorkspaceContext, document_id: uuid.UUID) -> DocumentOut:
    doc = await get_document(db, ctx, document_id)
    if not ctx.role.at_least(Role.MEMBER):
        raise Forbidden("Viewers can't reprocess documents", code="insufficient_role")
    if doc.status != "failed":
        raise Conflict("Only documents that failed can be processed again", code="not_failed")
    doc.status, doc.error_code, doc.error_message = "queued", None, None
    enqueue(db, kind="index_document", workspace_id=ctx.id, document_id=doc.id)
    await db.commit()
    await db.refresh(doc)
    from app.workers.runner import nudge_runner

    nudge_runner()
    return (await to_out(db, ctx, [doc]))[0]


async def download_target(ctx: WorkspaceContext, doc: Document) -> str | None:
    """Presigned URL for S3/R2, or None when the API must stream the file itself (local)."""
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        return None
    return await storage.presigned_download_url(
        doc.storage_key, doc.original_filename, doc.mime_type
    )
