import uuid
from typing import Annotated

from fastapi import APIRouter, File, Path, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import DB, MemberCtx, ViewerCtx
from app.core.config import get_settings
from app.core.errors import AppError
from app.integrations.storage import LocalStorage, content_disposition, get_storage
from app.schemas.documents import (
    CollectionCreate,
    CollectionDocumentsChange,
    CollectionOut,
    CollectionUpdate,
    DocumentList,
    DocumentOut,
    DocumentUpdate,
    DownloadOut,
    FileType,
    PageOut,
    SortOrder,
    UploadResult,
)
from app.services import collection_service as collections
from app.services import document_service as documents

router = APIRouter(tags=["documents"])
WS = "/workspaces/{workspace_id}"
NO_CONTENT = status.HTTP_204_NO_CONTENT


class PayloadTooLarge(AppError):
    status_code, code, title = 413, "payload_too_large", "Upload too large"


# ---------------------------------------------------------------- documents


@router.post(
    f"{WS}/documents",
    response_model=list[UploadResult],
    summary="Upload PDF/DOCX/TXT files (one result per file)",
)
async def upload_documents(
    request: Request,
    ctx: MemberCtx,
    db: DB,
    files: Annotated[list[UploadFile], File(description="1-10 files")],
) -> list[UploadResult]:
    s = get_settings()
    # Reject obviously oversized requests early (each file is also capped while streaming).
    declared = int(request.headers.get("content-length") or 0)
    if declared > s.max_files_per_upload * s.max_upload_bytes + 1024 * 1024:
        raise PayloadTooLarge(f"Each file can be at most {s.max_upload_mb} MB.")
    return await documents.upload_files(db, ctx, files)


@router.get(f"{WS}/documents", response_model=DocumentList)
async def list_documents(
    ctx: ViewerCtx,
    db: DB,
    q: Annotated[str | None, Query(max_length=200)] = None,
    type: Annotated[FileType | None, Query()] = None,
    status_: Annotated[
        str | None, Query(alias="status", pattern="^(queued|processing|ready|failed)$")
    ] = None,
    collection_id: uuid.UUID | None = None,
    sort: SortOrder = "newest",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    return await documents.list_documents(
        db,
        ctx,
        q=q,
        file_type=type,
        status=status_,
        collection_id=collection_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get(f"{WS}/documents/{{document_id}}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, ctx: ViewerCtx, db: DB) -> DocumentOut:
    doc = await documents.get_document(db, ctx, document_id)
    return (await documents.to_out(db, ctx, [doc]))[0]


@router.patch(f"{WS}/documents/{{document_id}}", response_model=DocumentOut)
async def rename_document(
    document_id: uuid.UUID, body: DocumentUpdate, ctx: MemberCtx, db: DB
) -> DocumentOut:
    return await documents.rename(db, ctx, document_id, body.title)


@router.delete(
    f"{WS}/documents/{{document_id}}",
    status_code=NO_CONTENT,
    summary="Delete a document (its text is removed from search immediately)",
)
async def delete_document(document_id: uuid.UUID, ctx: MemberCtx, db: DB) -> Response:
    await documents.delete_document(db, ctx, document_id)
    return Response(status_code=NO_CONTENT)


@router.post(f"{WS}/documents/{{document_id}}/reprocess", response_model=DocumentOut)
async def reprocess_document(document_id: uuid.UUID, ctx: MemberCtx, db: DB) -> DocumentOut:
    return await documents.reprocess(db, ctx, document_id)


@router.get(f"{WS}/documents/{{document_id}}/pages/{{page_number}}", response_model=PageOut)
async def get_page(
    document_id: uuid.UUID,
    page_number: Annotated[int, Path(ge=1, le=10_000)],
    ctx: ViewerCtx,
    db: DB,
) -> PageOut:
    return await documents.get_page(db, ctx, document_id, page_number)


@router.get(
    f"{WS}/documents/{{document_id}}/download",
    response_model=DownloadOut,
    summary="A short-lived URL to download the original file",
)
async def download_link(document_id: uuid.UUID, ctx: ViewerCtx, db: DB) -> DownloadOut:
    doc = await documents.get_document(db, ctx, document_id)
    url = await documents.download_target(ctx, doc)
    if url is None:  # local storage: the API streams the file itself (still authorized)
        url = f"/api/v1/workspaces/{ctx.id}/documents/{doc.id}/file"
    return DownloadOut(url=url, expires_in=get_settings().download_url_ttl_seconds)


@router.get(f"{WS}/documents/{{document_id}}/file", include_in_schema=False)
async def download_file(document_id: uuid.UUID, ctx: ViewerCtx, db: DB) -> FileResponse:
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise AppError("Use the download link instead", code="not_supported")
    doc = await documents.get_document(db, ctx, document_id)
    return FileResponse(
        storage.local_path(doc.storage_key),
        media_type=doc.mime_type,
        headers={"Content-Disposition": content_disposition(doc.original_filename)},
    )


# ---------------------------------------------------------------- collections


@router.get(f"{WS}/collections", response_model=list[CollectionOut], tags=["collections"])
async def list_collections(ctx: ViewerCtx, db: DB) -> list[CollectionOut]:
    return await collections.list_collections(db, ctx)


@router.post(
    f"{WS}/collections",
    response_model=CollectionOut,
    status_code=status.HTTP_201_CREATED,
    tags=["collections"],
)
async def create_collection(body: CollectionCreate, ctx: ViewerCtx, db: DB) -> CollectionOut:
    return await collections.create(db, ctx, body.name, body.description)


@router.patch(
    f"{WS}/collections/{{collection_id}}", response_model=CollectionOut, tags=["collections"]
)
async def update_collection(
    collection_id: uuid.UUID, body: CollectionUpdate, ctx: ViewerCtx, db: DB
) -> CollectionOut:
    return await collections.update(db, ctx, collection_id, body.name, body.description)


@router.delete(f"{WS}/collections/{{collection_id}}", status_code=NO_CONTENT, tags=["collections"])
async def delete_collection(collection_id: uuid.UUID, ctx: ViewerCtx, db: DB) -> Response:
    await collections.delete_collection(db, ctx, collection_id)
    return Response(status_code=NO_CONTENT)


@router.put(
    f"{WS}/collections/{{collection_id}}/documents",
    response_model=CollectionOut,
    tags=["collections"],
    summary="Add documents to a collection (idempotent)",
)
async def add_to_collection(
    collection_id: uuid.UUID, body: CollectionDocumentsChange, ctx: ViewerCtx, db: DB
) -> CollectionOut:
    return await collections.add_documents(db, ctx, collection_id, body.document_ids)


@router.delete(
    f"{WS}/collections/{{collection_id}}/documents",
    response_model=CollectionOut,
    tags=["collections"],
)
async def remove_from_collection(
    collection_id: uuid.UUID, body: CollectionDocumentsChange, ctx: ViewerCtx, db: DB
) -> CollectionOut:
    return await collections.remove_documents(db, ctx, collection_id, body.document_ids)
