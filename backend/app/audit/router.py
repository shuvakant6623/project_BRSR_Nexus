"""Audit trail API (spec §15). Read-only: no update/delete paths exist, and a
database trigger additionally rejects mutations (Phase 2 migration)."""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.db.session import get_db
from app.models import AppUser, AuditEvent
from app.models.enums import AuditAction, UserRole

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

READ_ROLES = (UserRole.ADMIN, UserRole.ESG_MANAGER, UserRole.REVIEWER,
              UserRole.MANAGEMENT, UserRole.ASSESSOR)


class AuditOut(BaseModel):
    id: uuid.UUID
    action: AuditAction
    actor: str
    entity_id: str | None
    metric_code: str | None
    object_type: str
    object_id: str | None
    old_value: dict | None
    new_value: dict | None
    reason: str | None
    request_id: str | None
    created_at: object


@router.get("", response_model=list[AuditOut])
def list_audit(
    entity_id: uuid.UUID | None = Query(default=None),
    metric_code: str | None = Query(default=None),
    action: AuditAction | None = Query(default=None),
    object_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> list[AuditOut]:
    if user.role not in READ_ROLES:
        from fastapi import HTTPException
        from fastapi import status as http_status

        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN,
                            detail="Your role cannot read the audit trail")
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc())
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        # entity_id is stored as text for history resilience
        stmt = stmt.where(AuditEvent.entity_id.in_([str(s) for s in scoped_ids]))
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == str(entity_id))
    if metric_code:
        stmt = stmt.where(AuditEvent.metric_code == metric_code)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if object_type:
        stmt = stmt.where(AuditEvent.object_type == object_type)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return [
        AuditOut(
            id=e.id, action=e.action, actor=e.actor_label, entity_id=e.entity_id,
            metric_code=e.metric_code, object_type=e.object_type, object_id=e.object_id,
            old_value=e.old_value, new_value=e.new_value, reason=e.reason,
            request_id=e.request_id, created_at=e.created_at,
        )
        for e in rows
    ]


@router.get("/metric-value/{value_id}/history", response_model=list[AuditOut])
def value_history(
    value_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuditOut]:
    rows = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.object_type == "metric_value", AuditEvent.object_id == str(value_id))
            .order_by(AuditEvent.created_at)
        ).all()
    )
    return [
        AuditOut(
            id=e.id, action=e.action, actor=e.actor_label, entity_id=e.entity_id,
            metric_code=e.metric_code, object_type=e.object_type, object_id=e.object_id,
            old_value=e.old_value, new_value=e.new_value, reason=e.reason,
            request_id=e.request_id, created_at=e.created_at,
        )
        for e in rows
    ]
