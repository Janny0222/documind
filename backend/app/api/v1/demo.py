"""The shared, read-only demo workspace (see services/demo_service.py)."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, Current
from app.models import WorkspaceMember
from app.services import demo_service
from app.workers.runner import nudge_runner

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoStatus(BaseModel):
    available: bool
    joined: bool
    workspace_id: uuid.UUID | None = None


class DemoJoined(BaseModel):
    workspace_id: uuid.UUID


@router.get("", response_model=DemoStatus, summary="Is there a demo workspace, and am I in it?")
async def status(current: Current, db: DB) -> DemoStatus:
    ws = await demo_service.get_demo_workspace(db)
    if ws is None:
        return DemoStatus(available=False, joined=False)
    joined = (
        await db.execute(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == current.user.id,
            )
        )
    ).scalar_one_or_none() is not None
    return DemoStatus(available=True, joined=joined, workspace_id=ws.id)


@router.post("/join", response_model=DemoJoined, summary="Join the demo workspace as a viewer")
async def join(current: Current, db: DB) -> DemoJoined:
    workspace_id = await demo_service.join_demo(db, current.user)
    nudge_runner()  # in case a sample is still waiting to be indexed
    return DemoJoined(workspace_id=workspace_id)
