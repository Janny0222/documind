import uuid

from fastapi import APIRouter, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import DB, ViewerCtx
from app.core.rate_limit import enforce
from app.schemas.chat import (
    AiStatus,
    AskRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
)
from app.services import chat_service as chat

router = APIRouter(tags=["ai"])
WS = "/workspaces/{workspace_id}"

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",  # tell reverse proxies not to buffer the stream
    "Connection": "keep-alive",
}


def _stream(prepared: chat.PreparedQuestion) -> StreamingResponse:
    return StreamingResponse(
        chat.answer_stream(prepared), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get(
    f"{WS}/ai/status",
    response_model=AiStatus,
    summary="Is AI usable here, and how many questions are left today",
)
async def ai_status(ctx: ViewerCtx, db: DB) -> AiStatus:
    return await chat.ai_status(db, ctx)


@router.get(f"{WS}/conversations", response_model=list[ConversationOut])
async def list_conversations(ctx: ViewerCtx, db: DB) -> list[ConversationOut]:
    return await chat.list_conversations(db, ctx)


@router.post(
    f"{WS}/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED
)
async def create_conversation(body: ConversationCreate, ctx: ViewerCtx, db: DB) -> ConversationOut:
    return await chat.create_conversation(db, ctx, body.scope.model_dump(mode="json"), body.title)


@router.get(f"{WS}/conversations/{{conversation_id}}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, ctx: ViewerCtx, db: DB
) -> ConversationDetail:
    return await chat.conversation_detail(db, ctx, conversation_id)


@router.patch(f"{WS}/conversations/{{conversation_id}}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, ctx: ViewerCtx, db: DB
) -> ConversationOut:
    scope = body.scope.model_dump(mode="json") if body.scope else None
    return await chat.update_conversation(db, ctx, conversation_id, body.title, scope)


@router.delete(f"{WS}/conversations/{{conversation_id}}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, ctx: ViewerCtx, db: DB) -> Response:
    await chat.delete_conversation(db, ctx, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    f"{WS}/conversations/{{conversation_id}}/messages",
    summary="Ask a question; the answer streams back as Server-Sent Events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def ask(
    conversation_id: uuid.UUID, body: AskRequest, ctx: ViewerCtx, db: DB
) -> StreamingResponse:
    enforce(f"ask:user:{ctx.user.id}", 10, 60)  # burst guard on top of the daily cap
    prepared = await chat.prepare_question(db, ctx, conversation_id, body.content)
    return _stream(prepared)


@router.post(
    f"{WS}/conversations/{{conversation_id}}/messages/{{message_id}}/regenerate",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def regenerate(
    conversation_id: uuid.UUID, message_id: uuid.UUID, ctx: ViewerCtx, db: DB
) -> StreamingResponse:
    enforce(f"ask:user:{ctx.user.id}", 10, 60)
    prepared = await chat.prepare_regenerate(db, ctx, conversation_id, message_id)
    return _stream(prepared)
