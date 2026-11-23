"""Shared, read-only demo workspace.

One workspace (`is_demo`) holds synthetic sample documents from app/demo/samples. Any signed-in
user can join it as a *viewer*: they can read and ask, not upload, delete or invite. Their
conversations stay private (conversations are per user). A nightly cron calls `reset_demo`, which
removes everyone's demo conversations and restores the sample set.

The workspace is owned by an inactive system account that can never sign in.
"""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.logging import get_logger
from app.core.security import hash_password, new_opaque_token
from app.integrations.storage import document_key, get_storage
from app.models import Document, Role, User, Workspace, WorkspaceMember
from app.models.chat import Conversation
from app.rag.validation import MIME, FileKind
from app.services.auth_service import utcnow
from app.workers.queue import enqueue

log = get_logger(__name__)

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "demo" / "samples"
DEMO_OWNER_EMAIL = "demo-owner@documind.invalid"  # .invalid can never receive mail (RFC 2606)
DEMO_NAME = "Demo: Lumen & Pine"


def _samples() -> list[tuple[Path, bytes, str]]:
    out = []
    for path in sorted(SAMPLES_DIR.glob("*.txt")):
        data = path.read_bytes()
        out.append((path, data, hashlib.sha256(data).hexdigest()))
    return out


async def get_demo_workspace(db: AsyncSession) -> Workspace | None:
    return (
        await db.execute(select(Workspace).where(Workspace.is_demo.is_(True)).limit(1))
    ).scalar_one_or_none()


async def _owner(db: AsyncSession) -> User:
    owner = (
        await db.execute(select(User).where(User.email == DEMO_OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(
            email=DEMO_OWNER_EMAIL,
            # Random password nobody knows, and is_active=False blocks sign-in regardless.
            password_hash=hash_password(new_opaque_token()),
            display_name="DocuMind Demo",
            is_active=False,
        )
        db.add(owner)
        await db.flush()
    return owner


async def seed_demo(db: AsyncSession) -> tuple[uuid.UUID, int]:
    """Create the demo workspace if needed and queue any missing sample documents.
    Idempotent: safe to run on every startup. Returns (workspace id, documents queued)."""
    owner = await _owner(db)
    ws = await get_demo_workspace(db)
    if ws is None:
        ws = Workspace(
            name=DEMO_NAME,
            is_demo=True,
            # Sample content is synthetic, so the system owner allows AI processing up front.
            ai_consent_at=utcnow(),
            ai_consent_by=owner.id,
        )
        db.add(ws)
        await db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=Role.OWNER))

    docs = (
        await db.execute(
            select(Document).where(Document.workspace_id == ws.id, Document.deleted_at.is_(None))
        )
    ).scalars()
    existing: set[str] = set()
    queued = 0
    for doc in docs:
        existing.add(doc.sha256)
        if doc.status == "failed":  # e.g. a quota error last night: try again
            doc.status = "queued"
            enqueue(db, kind="index_document", workspace_id=ws.id, document_id=doc.id)
            queued += 1
    storage = get_storage()
    for path, data, sha in _samples():
        if sha in existing:
            continue
        doc_id = uuid.uuid4()
        key = document_key(ws.id, doc_id)
        await storage.put_file(key, path, MIME[FileKind.TXT])
        db.add(
            Document(
                id=doc_id,
                workspace_id=ws.id,
                uploaded_by=owner.id,
                title=path.stem,
                original_filename=path.name,
                mime_type=MIME[FileKind.TXT],
                size_bytes=len(data),
                storage_key=key,
                sha256=sha,
                status="queued",
                page_unit="section",
            )
        )
        enqueue(db, kind="index_document", workspace_id=ws.id, document_id=doc_id)
        queued += 1
    await db.commit()
    if queued:
        log.info("demo_seeded", workspace_id=str(ws.id), queued=queued)
    return ws.id, queued


async def reset_demo(db: AsyncSession) -> dict[str, int]:
    """Nightly: drop all demo conversations and restore the sample documents."""
    ws = await get_demo_workspace(db)
    if ws is None:
        _, queued = await seed_demo(db)
        return {"conversations_deleted": 0, "documents_queued": queued}
    result = await db.execute(delete(Conversation).where(Conversation.workspace_id == ws.id))
    deleted = int(getattr(result, "rowcount", 0) or 0)
    await db.commit()
    _, queued = await seed_demo(db)
    return {"conversations_deleted": deleted, "documents_queued": queued}


async def join_demo(db: AsyncSession, user: User) -> uuid.UUID:
    """Add the user to the demo workspace as a viewer (no-op if already a member)."""
    ws = await get_demo_workspace(db)
    if ws is None:
        raise NotFound(
            "The demo workspace isn't available on this server.", code="demo_unavailable"
        )
    member = await db.get(WorkspaceMember, (ws.id, user.id))
    if member is None:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER))
        await db.commit()
    return ws.id
