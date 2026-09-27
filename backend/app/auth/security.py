"""Password hashing and JWT creation/verification."""
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> tuple[str, str]:
    settings = get_settings()
    jti = str(uuid.uuid4())
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), jti


def create_access_token(user_id: str) -> tuple[str, str]:
    settings = get_settings()
    return _create_token(user_id, "access", timedelta(minutes=settings.jwt_access_expiry_minutes))


def create_refresh_token(user_id: str) -> tuple[str, str]:
    settings = get_settings()
    return _create_token(user_id, "refresh", timedelta(days=settings.jwt_refresh_expiry_days))


def decode_token(token: str, expected_type: str) -> dict:
    """Raises jwt.InvalidTokenError (or ValueError on wrong type)."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise ValueError("wrong token type")
    return payload
