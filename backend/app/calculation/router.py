"""Calculation API: trigger derived-metric recomputation."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.calculation import service
from app.db.session import get_db
from app.logging import request_id_var
from app.models import AppUser
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1/calculations", tags=["calculations"])


class CalculationRun(BaseModel):
    period_id: uuid.UUID
    entity_id: uuid.UUID | None = None


@router.post("/run")
def run_calculations(
    body: CalculationRun,
    request: Request,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER, UserRole.REVIEWER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only reviewers, ESG managers and admins may run calculations")
    entity_ids = None
    if body.entity_id:
        if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER) and body.entity_id not in scoped_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Entity outside your authorized scope")
        entity_ids = [body.entity_id]
    elif user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        entity_ids = sorted(scoped_ids)
    result = service.run_calculations(
        db, body.period_id, entity_ids=entity_ids, actor=user, request_id=request_id_var.get()
    )
    db.commit()
    return {"status": "completed", **result}
