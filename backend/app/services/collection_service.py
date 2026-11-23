import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound
from app.models import Collection, CollectionDocument, Document, Role
from app.schemas.documents import CollectionOut
from app.services.activity import record_activity
from app.services.workspace_service import WorkspaceContext


def _assert_member(ctx: WorkspaceContext) -> None:
    if not ctx.role.at_least(Role.MEMBER):
        raise Forbidden("Viewers can't change collections", code="insufficient_role")


async def _get(db: AsyncSession, ctx: WorkspaceContext, collection_id: uuid.UUID) -> Collection:
    col = (
        await db.execute(
            select(Collection).where(
                Collection.id == collection_id, Collection.workspace_id == ctx.id
            )
        )
    ).scalar_one_or_none()
    if col is None:
        raise NotFound("Collection not found")
    return col


async def _out(db: AsyncSession, cols: list[Collection]) -> list[CollectionOut]:
    if not cols:
        return []
    counts = dict(
        (
            await db.execute(
                select(CollectionDocument.collection_id, func.count())
                .join(Document, Document.id == CollectionDocument.document_id)
                .where(
                    CollectionDocument.collection_id.in_([c.id for c in cols]),
                    Document.deleted_at.is_(None),
                )
                .group_by(CollectionDocument.collection_id)
            )
        ).all()
    )
    return [
        CollectionOut(
            id=c.id,
            name=c.name,
            description=c.description,
            document_count=counts.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in cols
    ]


async def list_collections(db: AsyncSession, ctx: WorkspaceContext) -> list[CollectionOut]:
    cols = list(
        (
            await db.execute(
                select(Collection)
                .where(Collection.workspace_id == ctx.id)
                .order_by(func.lower(Collection.name))
            )
        )
        .scalars()
        .all()
    )
    return await _out(db, cols)


async def create(
    db: AsyncSession, ctx: WorkspaceContext, name: str, description: str | None
) -> CollectionOut:
    _assert_member(ctx)
    col = Collection(
        workspace_id=ctx.id, name=name, description=description or None, created_by=ctx.user.id
    )
    db.add(col)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "A collection with this name already exists", code="collection_exists"
        ) from exc
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="collection.created",
        target_type="collection",
        target_id=col.id,
        meta={"name": name},
    )
    await db.commit()
    await db.refresh(col)
    return (await _out(db, [col]))[0]


async def update(
    db: AsyncSession,
    ctx: WorkspaceContext,
    collection_id: uuid.UUID,
    name: str | None,
    description: str | None,
) -> CollectionOut:
    _assert_member(ctx)
    col = await _get(db, ctx, collection_id)
    if name is not None:
        col.name = name
    if description is not None:
        col.description = description or None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "A collection with this name already exists", code="collection_exists"
        ) from exc
    await db.refresh(col)
    return (await _out(db, [col]))[0]


async def delete_collection(
    db: AsyncSession, ctx: WorkspaceContext, collection_id: uuid.UUID
) -> None:
    """Deletes the grouping only - the documents stay in the workspace."""
    _assert_member(ctx)
    col = await _get(db, ctx, collection_id)
    await db.delete(col)
    record_activity(
        db,
        workspace_id=ctx.id,
        actor_id=ctx.user.id,
        action="collection.deleted",
        target_type="collection",
        target_id=collection_id,
        meta={"name": col.name},
    )
    await db.commit()


async def _live_doc_ids(
    db: AsyncSession, ctx: WorkspaceContext, ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    found = list(
        (
            await db.execute(
                select(Document.id).where(
                    Document.id.in_(ids),
                    Document.workspace_id == ctx.id,
                    Document.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if len(found) != len(set(ids)):
        raise NotFound("One or more documents were not found")
    return found


async def add_documents(
    db: AsyncSession, ctx: WorkspaceContext, collection_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> CollectionOut:
    _assert_member(ctx)
    col = await _get(db, ctx, collection_id)
    ids = await _live_doc_ids(db, ctx, document_ids)
    # Idempotent: adding a document that's already there is a no-op.
    await db.execute(
        pg_insert(CollectionDocument)
        .values([{"collection_id": col.id, "document_id": d, "workspace_id": ctx.id} for d in ids])
        .on_conflict_do_nothing()
    )
    await db.commit()
    return (await _out(db, [col]))[0]


async def remove_documents(
    db: AsyncSession, ctx: WorkspaceContext, collection_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> CollectionOut:
    _assert_member(ctx)
    col = await _get(db, ctx, collection_id)
    await db.execute(
        delete(CollectionDocument).where(
            CollectionDocument.collection_id == col.id,
            CollectionDocument.document_id.in_(document_ids),
        )
    )
    await db.commit()
    return (await _out(db, [col]))[0]
