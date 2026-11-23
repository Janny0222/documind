from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.cookies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    existing_csrf,
    set_auth_cookies,
    set_csrf_cookie,
)
from app.api.deps import DB, Current
from app.core.config import get_settings
from app.core.errors import PROBLEM_JSON, Unauthorized, problem
from app.core.rate_limit import rate_limit
from app.core.security import decode_access_token
from app.models import User
from app.schemas.auth import (
    CsrfOut,
    EmailRequest,
    LoginRequest,
    MessageOut,
    RegisterRequest,
    ResetPasswordRequest,
    SessionOut,
    TokenRequest,
    UserOut,
)
from app.services import auth_service
from app.services.auth_service import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

_misc_limit = Depends(rate_limit("auth_misc", lambda: get_settings().auth_misc_limit_per_minute))
_login_limit = Depends(rate_limit("login", lambda: get_settings().login_ip_limit_per_minute))


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        theme=user.theme,
        created_at=user.created_at,
    )


def _session_response(response: Response, user: User, tokens: IssuedTokens) -> SessionOut:
    set_auth_cookies(response, tokens)
    return SessionOut(user=user_out(user), access_expires_at=tokens.access_expires_at)


@router.get("/csrf", response_model=CsrfOut, summary="Get (or create) the CSRF token cookie")
async def csrf(request: Request, response: Response) -> CsrfOut:
    return CsrfOut(csrf_token=set_csrf_cookie(response, existing_csrf(request)))


@router.post(
    "/register",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_misc_limit],
)
async def register(
    body: RegisterRequest, request: Request, response: Response, db: DB
) -> SessionOut:
    user, tokens = await auth_service.register(
        db,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        user_agent=request.headers.get("user-agent"),
    )
    return _session_response(response, user, tokens)


@router.post("/login", response_model=SessionOut, dependencies=[_login_limit])
async def login(body: LoginRequest, request: Request, response: Response, db: DB) -> SessionOut:
    user, tokens = await auth_service.login(
        db, email=body.email, password=body.password, user_agent=request.headers.get("user-agent")
    )
    return _session_response(response, user, tokens)


@router.post(
    "/refresh",
    response_model=SessionOut,
    summary="Rotate the refresh token",
    responses={401: {"description": "Session expired (cookies cleared) or refresh_race"}},
)
async def refresh(request: Request, response: Response, db: DB) -> SessionOut | JSONResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    try:
        if not raw:
            raise Unauthorized("Session expired", code="session_expired")
        user, tokens = await auth_service.refresh(db, raw)
    except Unauthorized as exc:
        error = JSONResponse(
            problem(401, exc.code, exc.title, exc.detail), status_code=401, media_type=PROBLEM_JSON
        )
        if exc.code != "refresh_race":  # a benign race keeps the (already rotated) cookies
            clear_auth_cookies(error)
        return error
    return _session_response(response, user, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: DB) -> Response:
    """Works even with an expired access token: falls back to the refresh cookie's session."""
    session_id = None
    if (token := request.cookies.get(ACCESS_COOKIE)) and (claims := decode_access_token(token)):
        session_id = claims.session_id
    elif raw := request.cookies.get(REFRESH_COOKIE):
        session_id = await auth_service.session_id_for_refresh_token(db, raw)
    if session_id:
        await auth_service.revoke_session(db, session_id, "logout")
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.post(
    "/forgot-password",
    response_model=MessageOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_misc_limit],
)
async def forgot_password(body: EmailRequest, db: DB) -> MessageOut:
    await auth_service.forgot_password(db, body.email)
    return MessageOut(detail="If an account exists for that email, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageOut, dependencies=[_misc_limit])
async def reset_password(body: ResetPasswordRequest, db: DB) -> MessageOut:
    await auth_service.reset_password(db, body.token, body.new_password)
    return MessageOut(detail="Password updated. Please sign in again.")


@router.post("/verify-email", response_model=MessageOut, dependencies=[_misc_limit])
async def verify_email(body: TokenRequest, db: DB) -> MessageOut:
    await auth_service.verify_email(db, body.token)
    return MessageOut(detail="Email verified.")


@router.post(
    "/resend-verification",
    response_model=MessageOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_misc_limit],
)
async def resend_verification(current: Current, db: DB) -> MessageOut:
    await auth_service.resend_verification(db, current.user)
    return MessageOut(detail="If your email is unverified, a new link has been sent.")
