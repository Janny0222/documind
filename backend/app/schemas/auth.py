import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

from app.core.config import get_settings

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Token = Annotated[str, StringConstraints(min_length=20, max_length=200)]

# Small deny-list of the most common passwords that pass a length check.
_COMMON = {
    "password123",
    "password1234",
    "1234567890",
    "qwertyuiop",
    "iloveyou12",
    "passw0rd123",
    "123456789012",
    "qwerty12345",
    "letmein1234",
    "administrator",
    "welcome123",
    "abcdefghij",
}


def _check_password(value: str) -> str:
    s = get_settings()
    if len(value) < s.password_min_length:
        raise ValueError(f"Password must be at least {s.password_min_length} characters")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters")
    if value.lower() in _COMMON:
        raise ValueError("This password is too common")
    return value


Password = Annotated[str, AfterValidator(_check_password)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: DisplayName


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class TokenRequest(BaseModel):
    token: Token


class EmailRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: Token
    new_password: Password


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Password


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    email_verified: bool
    theme: Literal["system", "light", "dark"]
    created_at: datetime


class UpdateMeRequest(BaseModel):
    display_name: DisplayName | None = None
    theme: Literal["system", "light", "dark"] | None = None


class SessionOut(BaseModel):
    user: UserOut
    access_expires_at: datetime


class CsrfOut(BaseModel):
    csrf_token: str = Field(description="Also set as the dm_csrf cookie; echo it in X-CSRF-Token.")


class MessageOut(BaseModel):
    detail: str
