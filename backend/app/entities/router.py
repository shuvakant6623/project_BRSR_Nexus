"""Entity CRUD API. Writes are ADMIN-only; reads are scope-filtered server-side."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import get_current_user, get_scoped_entity_ids, require_roles
from app.db.session import get_db
from app.entities.service import EntityValidationError, create_entity, update_entity
from app.models import AppUser, Entity
from app.models.enums import AuditAction, EntityType, UserRole

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])
require_admin = require_roles(UserRole.ADMIN)


class EntityOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    entity_type: EntityType
    name: str
    is_active: bool
    effective_from: date
    effective_to: date | None
    reporting_boundary_notes: str | None


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    entity_type: EntityType
    parent_id: uuid.UUID | None = None
    effective_from: date
    effective_to: date | None = None
    reporting_boundary_notes: str | None = None


class EntityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    reporting_boundary_notes: str | None = None


def _to_out(entity: Entity) -> EntityOut:
    return EntityOut(
        id=entity.id,
        parent_id=entity.parent_id,
        entity_type=entity.entity_type,
        name=entity.name,
        is_active=entity.is_active,
        effective_from=entity.effective_from,
        effective_to=entity.effective_to,
        reporting_boundary_notes=entity.reporting_boundary_notes,
    )


@router.get("", response_model=list[EntityOut])
def list_entities(
    include_inactive: bool = Query(default=False),
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> list[EntityOut]:
    stmt = select(Entity).order_by(Entity.name)
    if not include_inactive:
        stmt = stmt.where(Entity.is_active.is_(True))
    entities = list(db.scalars(stmt).all())
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        entities = [e for e in entities if e.id in scoped_ids]
    return [_to_out(e) for e in entities]


@router.get("/{entity_id}", response_model=EntityOut)
def get_entity(
    entity_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> EntityOut:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER) and entity_id not in scoped_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Entity outside your authorized scope",
        )
    return _to_out(entity)


@router.post("", response_model=EntityOut, status_code=201)
def create(
    body: EntityCreate,
    user: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EntityOut:
    try:
        entity = create_entity(
            db,
            name=body.name,
            entity_type=body.entity_type,
            parent_id=body.parent_id,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
            reporting_boundary_notes=body.reporting_boundary_notes,
        )
        record(
            db, action=AuditAction.CREATED, object_type="entity", object_id=entity.id,
            actor_id=user.id, actor_label=user.email, entity_id=entity.id,
            new_value={"name": entity.name, "entity_type": entity.entity_type.value,
                       "parent_id": str(entity.parent_id) if entity.parent_id else None},
        )
        db.commit()
    except EntityValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.refresh(entity)
    return _to_out(entity)


@router.patch("/{entity_id}", response_model=EntityOut)
def patch(
    entity_id: uuid.UUID,
    body: EntityPatch,
    user: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EntityOut:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    changes = body.model_dump(exclude_unset=True)
    old = {"name": entity.name, "parent_id": str(entity.parent_id) if entity.parent_id else None,
           "is_active": entity.is_active}
    try:
        structure_changed = "parent_id" in changes and changes["parent_id"] != entity.parent_id
        update_entity(db, entity, changes)
        if structure_changed:
            from app.consolidation.service import mark_entity_traces_stale

            mark_entity_traces_stale(db, entity.id)
        record(
            db, action=AuditAction.UPDATED, object_type="entity", object_id=entity.id,
            actor_id=user.id, actor_label=user.email, entity_id=entity.id,
            old_value=old,
            new_value={"name": entity.name, "parent_id": str(entity.parent_id) if entity.parent_id else None,
                       "is_active": entity.is_active},
            reason="entity update via API",
        )
        db.commit()
    except EntityValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.refresh(entity)
    return _to_out(entity)
