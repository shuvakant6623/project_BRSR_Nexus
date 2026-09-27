"""Admin user management endpoints."""
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import require_roles
from app.auth.security import hash_password
from app.db.session import get_db
from app.models import AppUser, Entity, UserEntityScope
from app.models.enums import AuditAction, UserRole

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str
    password: str
    role: UserRole


@router.get("", response_model=list[UserOut])
def list_users(
    _user: AppUser = Depends(require_roles(UserRole.ADMIN, UserRole.ESG_MANAGER)),
    db: Session = Depends(get_db),
) -> list[AppUser]:
    return list(db.scalars(select(AppUser).order_by(AppUser.email)).all())


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    _user: AppUser = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AppUser:
    existing = db.scalar(select(AppUser).where(AppUser.email == body.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = AppUser(
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.flush()
    record(db, action=AuditAction.CREATED, object_type="app_user", object_id=user.id,
           actor_id=_user.id, actor_label=_user.email, new_value={"email": body.email, "role": body.role.value})
    db.commit()
    db.refresh(user)
    return user


class ScopeGrant(BaseModel):
    entity_id: UUID


@router.post("/{user_id}/scopes", status_code=201)
def grant_entity_scope(
    user_id: UUID,
    body: ScopeGrant,
    _user: AppUser = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(AppUser, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if db.get(Entity, body.entity_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    exists = db.scalar(
        select(UserEntityScope).where(
            UserEntityScope.user_id == user_id, UserEntityScope.entity_id == body.entity_id
        )
    )
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scope already granted")
    scope = UserEntityScope(user_id=user_id, entity_id=body.entity_id)
    db.add(scope)
    db.flush()
    record(db, action=AuditAction.CREATED, object_type="user_entity_scope", object_id=scope.id,
           actor_id=_user.id, actor_label=_user.email,
           new_value={"user_id": str(user_id), "entity_id": str(body.entity_id)})
    db.commit()
    return {"user_id": str(user_id), "entity_id": str(body.entity_id)}
