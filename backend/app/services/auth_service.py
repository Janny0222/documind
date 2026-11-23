"""Authentication use-cases. HTTP concerns (cookies, status codes) stay in the API layer."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, TooManyRequests, Unauthorized
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.models import AuthSession, AuthToken, RefreshToken, Role, User, Workspace, WorkspaceMember
from app.services.activity import record_activity
from app.services.email import send_email

log = get_logger(__name__)

LOGIN_FAILURE_WINDOW = 15 * 60


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID


@dataclass(frozen=True)
class CurrentUser:
    user: User
    session_id: uuid.UUID


# ---------------------------------------------------------------- sessions


async def _issue_tokens(db: AsyncSession, user: User, session: AuthSession) -> IssuedTokens:
    s = get_settings()
    now = utcnow()
    refresh = new_opaque_token()
    refresh_expires = now + timedelta(days=s.refresh_token_ttl_days)  # sliding session
    session.expires_at = refresh_expires
    session.last_used_at = now
    db.add(
        RefreshToken(
            session_id=session.id, token_hash=hash_token(refresh), expires_at=refresh_expires
        )
    )
    access, access_expires = create_access_token(user.id, session.id)
    return IssuedTokens(access, access_expires, refresh, refresh_expires, session.id)


async def _start_session(db: AsyncSession, user: User, user_agent: str | None) -> IssuedTokens:
    session = AuthSession(
        user_id=user.id,
        user_agent=(user_agent or "")[:255] or None,
        expires_at=utcnow(),  # set properly by _issue_tokens
    )
    db.add(session)
    await db.flush()
    return await _issue_tokens(db, user, session)


async def revoke_session(db: AsyncSession, session_id: uuid.UUID, reason: str) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )


async def revoke_all_sessions(
    db: AsyncSession, user_id: uuid.UUID, reason: str, *, except_session: uuid.UUID | None = None
) -> None:
    stmt = update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if except_session is not None:
        stmt = stmt.where(AuthSession.id != except_session)
    await db.execute(stmt.values(revoked_at=utcnow(), revoked_reason=reason))


async def resolve_access(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> CurrentUser | None:
    """Validates that the JWT's session is still live (this is what makes logout immediate)."""
    row = (
        await db.execute(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                AuthSession.id == session_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
        )
    ).scalar_one_or_none()
    return CurrentUser(row, session_id) if row else None


# ---------------------------------------------------------------- register / login


async def register(
    db: AsyncSession, *, email: str, password: str, display_name: str, user_agent: str | None
) -> tuple[User, IssuedTokens]:
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise Conflict("An account with this email already exists", code="email_taken")

    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:  # concurrent registration with the same email
        await db.rollback()
        raise Conflict("An account with this email already exists", code="email_taken") from exc

    workspace = Workspace(name=f"{display_name}'s Workspace"[:80], is_personal=True)
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
    record_activity(
        db,
        workspace_id=workspace.id,
        actor_id=user.id,
        action="workspace.created",
        target_type="workspace",
        target_id=workspace.id,
    )

    verify_token = await _create_auth_token(db, user, "verify_email")
    tokens = await _start_session(db, user, user_agent)
    await db.commit()

    await _send_verification(user, verify_token)
    return user, tokens


async def login(
    db: AsyncSession, *, email: str, password: str, user_agent: str | None
) -> tuple[User, IssuedTokens]:
    s = get_settings()
    failure_key = f"login_fail:email:{email.lower()}"
    if s.rate_limit_enabled and (
        retry := rate_limit.limiter.peek_exceeded(
            failure_key, s.login_email_failures_per_15_min, LOGIN_FAILURE_WINDOW
        )
    ):
        raise TooManyRequests(
            "Too many failed attempts. Try again later.", headers={"Retry-After": str(retry)}
        )

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    valid, new_hash = verify_password(password, user.password_hash if user else None)
    if not user or not valid or not user.is_active:
        if s.rate_limit_enabled:
            rate_limit.limiter.hit(
                failure_key, s.login_email_failures_per_15_min, LOGIN_FAILURE_WINDOW
            )
        raise Unauthorized("Invalid email or password", code="invalid_credentials")

    if s.email_verification_required and user.email_verified_at is None:
        raise Forbidden("Please verify your email address first", code="email_not_verified")

    if new_hash:
        user.password_hash = new_hash
    rate_limit.limiter.clear(failure_key)
    tokens = await _start_session(db, user, user_agent)
    await db.commit()
    return user, tokens


async def refresh(db: AsyncSession, raw_token: str) -> tuple[User, IssuedTokens]:
    s = get_settings()
    now = utcnow()
    row = (
        await db.execute(
            select(RefreshToken, AuthSession, User)
            .join(AuthSession, AuthSession.id == RefreshToken.session_id)
            .join(User, User.id == AuthSession.user_id)
            .where(RefreshToken.token_hash == hash_token(raw_token))
            .with_for_update(of=RefreshToken)  # serialize concurrent refreshes of one token
        )
    ).first()
    if row is None:
        raise Unauthorized("Session expired", code="session_expired")
    token, session, user = row

    if (
        session.revoked_at is not None
        or session.expires_at <= now
        or token.expires_at <= now
        or not user.is_active
    ):
        raise Unauthorized("Session expired", code="session_expired")

    if token.used_at is not None:
        if now - token.used_at <= timedelta(seconds=s.refresh_reuse_grace_seconds):
            # Two tabs refreshed at once; the other one already holds the new cookie.
            raise Unauthorized("Refresh already in progress", code="refresh_race")
        await revoke_session(db, session.id, "refresh_token_reuse")
        await db.commit()
        log.warning(
            "refresh_token_reuse_detected", user_id=str(user.id), session_id=str(session.id)
        )
        raise Unauthorized("Session expired", code="session_expired")

    token.used_at = now
    tokens = await _issue_tokens(db, user, session)
    await db.commit()
    return user, tokens


async def session_id_for_refresh_token(db: AsyncSession, raw_token: str) -> uuid.UUID | None:
    return (
        await db.execute(
            select(RefreshToken.session_id).where(RefreshToken.token_hash == hash_token(raw_token))
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------- email tokens


async def _create_auth_token(db: AsyncSession, user: User, purpose: str) -> str:
    s = get_settings()
    ttl = (
        timedelta(minutes=s.password_reset_ttl_minutes)
        if purpose == "reset_password"
        else timedelta(hours=s.email_token_ttl_hours)
    )
    # Only the newest token of a purpose is valid.
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None)
        )
        .values(used_at=utcnow())
    )
    raw = new_opaque_token()
    db.add(
        AuthToken(
            user_id=user.id, purpose=purpose, token_hash=hash_token(raw), expires_at=utcnow() + ttl
        )
    )
    return raw


async def _consume_auth_token(db: AsyncSession, raw: str, purpose: str) -> User:
    row = (
        await db.execute(
            select(AuthToken, User)
            .join(User, User.id == AuthToken.user_id)
            .where(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose)
            .with_for_update(of=AuthToken)
        )
    ).first()
    if row is None or row[0].used_at is not None or row[0].expires_at <= utcnow():
        raise Unauthorized("This link is invalid or has expired", code="invalid_token")
    row[0].used_at = utcnow()
    return row[1]


# Tokens go in the URL *fragment*: browsers never send fragments to servers or in Referer headers.
async def _send_verification(user: User, raw: str) -> None:
    link = f"{get_settings().frontend_url}/verify-email#token={raw}"
    await send_email(user.email, "Verify your DocuMind email", f"Confirm your email: {link}")


async def resend_verification(db: AsyncSession, user: User) -> None:
    if user.email_verified_at is not None:
        return
    raw = await _create_auth_token(db, user, "verify_email")
    await db.commit()
    await _send_verification(user, raw)


async def verify_email(db: AsyncSession, raw: str) -> None:
    user = await _consume_auth_token(db, raw, "verify_email")
    user.email_verified_at = user.email_verified_at or utcnow()
    await db.commit()


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Always succeeds from the caller's view, so it can't be used to discover accounts."""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active:
        return
    raw = await _create_auth_token(db, user, "reset_password")
    await db.commit()
    link = f"{get_settings().frontend_url}/reset-password#token={raw}"
    await send_email(user.email, "Reset your DocuMind password", f"Reset your password: {link}")


async def reset_password(db: AsyncSession, raw: str, new_password: str) -> None:
    user = await _consume_auth_token(db, raw, "reset_password")
    user.password_hash = hash_password(new_password)
    # Proving control of the inbox also verifies it.
    user.email_verified_at = user.email_verified_at or utcnow()
    await revoke_all_sessions(db, user.id, "password_reset")
    await db.commit()


async def change_password(
    db: AsyncSession, current: CurrentUser, current_password: str, new_password: str
) -> None:
    valid, _ = verify_password(current_password, current.user.password_hash)
    if not valid:
        raise Unauthorized("Current password is incorrect", code="invalid_credentials")
    current.user.password_hash = hash_password(new_password)
    await revoke_all_sessions(
        db, current.user.id, "password_changed", except_session=current.session_id
    )
    await db.commit()
