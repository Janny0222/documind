from fastapi import APIRouter, Response, status

from app.api.deps import DB, Current
from app.api.v1.auth import user_out
from app.schemas.auth import ChangePasswordRequest, UpdateMeRequest, UserOut
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(current: Current) -> UserOut:
    return user_out(current.user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: UpdateMeRequest, current: Current, db: DB) -> UserOut:
    if body.display_name is not None:
        current.user.display_name = body.display_name
    if body.theme is not None:
        current.user.theme = body.theme
    await db.commit()
    await db.refresh(current.user)
    return user_out(current.user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password (signs out all other sessions)",
)
async def change_password(body: ChangePasswordRequest, current: Current, db: DB) -> Response:
    await auth_service.change_password(db, current, body.current_password, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
