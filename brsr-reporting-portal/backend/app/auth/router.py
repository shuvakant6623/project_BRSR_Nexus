"""Authentication endpoints: login, refresh, logout, me."""
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.auth.security import create_access_token, create_refresh_token, decode_token, verify_password
from app.config import get_settings
from app.db.session import get_db
from app.infra.redis import get_redis
from app.models import AppUser
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

LOGIN_RATELIMIT_MAX_FAILURES = 10
LOGIN_RATELIMIT_WINDOW_SECONDS = 900
REFRESH_DENYLIST_PREFIX = "auth:refresh_denied:"


class LoginRequest(BaseModel):
    # plain pattern rather than EmailStr: email-validator rejects reserved
    # domains like .local used by the demo deployment
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


def _check_login_ratelimit(request: Request, email: str) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"auth:login_failures:{client_ip}:{email}"
    failures = int(get_redis().get(key) or 0)
    if failures >= LOGIN_RATELIMIT_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts; try again later",
        )
    request.state.login_failure_key = key


def _record_login_failure(request: Request) -> None:
    key = getattr(request.state, "login_failure_key", None)
    if key:
        r = get_redis()
        count = r.incr(key)
        if count == 1:
            r.expire(key, LOGIN_RATELIMIT_WINDOW_SECONDS)


class PublicUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    entity_scope_ids: list[uuid.UUID]


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    _check_login_ratelimit(request, body.email)
    user = db.scalar(select(AppUser).where(AppUser.email == body.email))
    if user is None or not verify_password(body.password, user.hashed_password):
        _record_login_failure(request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    access, _ = create_access_token(str(user.id))
    refresh, refresh_jti = create_refresh_token(str(user.id))
    settings = get_settings()
    get_redis().setex(
        f"auth:refresh:{refresh_jti}",
        settings.jwt_refresh_expiry_days * 86400,
        str(user.id),
    )
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    r = get_redis()
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except (jwt.InvalidTokenError, ValueError, jwt.ExpiredSignatureError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    jti = payload["jti"]
    if r.exists(f"{REFRESH_DENYLIST_PREFIX}{jti}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")
    user = db.get(AppUser, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer active")

    # rotation: old refresh token becomes unusable
    r.setex(f"{REFRESH_DENYLIST_PREFIX}{jti}", settings_ttl(jti), "1")
    access, _ = create_access_token(str(user.id))
    new_refresh, _ = create_refresh_token(str(user.id))
    return TokenPair(access_token=access, refresh_token=new_refresh)


def settings_ttl(jti: str) -> int:
    # denylist entry lives for the remaining validity of the rotated token;
    # cap at the configured refresh lifetime
    return get_settings().jwt_refresh_expiry_days * 86400


@router.post("/logout", status_code=204)
def logout(body: RefreshRequest) -> Response:
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except Exception:
        return Response(status_code=204)
    get_redis().setex(f"{REFRESH_DENYLIST_PREFIX}{payload['jti']}", settings_ttl(payload["jti"]), "1")
    return Response(status_code=204)


@router.get("/me", response_model=PublicUser)
def me(
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
) -> PublicUser:
    return PublicUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        entity_scope_ids=sorted(scoped_ids),
    )
