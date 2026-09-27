"""Server-side authorization dependencies. Frontend hiding is NOT security."""
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.db.session import get_db
from app.entities.service import get_user_scoped_entity_ids
from app.models import AppUser
from app.models.enums import UserRole

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AppUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except Exception:
        raise unauthorized
    user = db.get(AppUser, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    request_state_user = payload
    return user


def get_scoped_entity_ids(
    request: Request, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> set[uuid.UUID]:
    """Allowed entity ids for this user (resolved server-side, cached per request)."""
    if user.role in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        from sqlalchemy import select

        from app.models import Entity

        return set(db.scalars(select(Entity.id)).all())
    if not hasattr(request.state, "scoped_entity_ids"):
        request.state.scoped_entity_ids = get_user_scoped_entity_ids(db, user)
    return request.state.scoped_entity_ids


def require_entity_access(entity_id: uuid.UUID):
    """Dependency factory: fails 403 unless entity_id is within user scope."""

    def _check(
        request: Request,
        user: AppUser = Depends(get_current_user),
        scoped: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    ) -> None:
        if user.role in (UserRole.ADMIN, UserRole.ESG_MANAGER):
            return
        if entity_id not in scoped:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Entity outside your authorized scope")

    return _check


def require_roles(*roles: UserRole):
    def _check(user: AppUser = Depends(get_current_user)) -> AppUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _check
