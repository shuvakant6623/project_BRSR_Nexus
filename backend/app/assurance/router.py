"""Assurance readiness API endpoints."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assurance import service
from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.db.session import get_db
from app.models import AppUser, ReportingPeriod
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1/assurance", tags=["assurance"])


class IndicatorReadinessOut(BaseModel):
    metric_code: str
    section: str
    principle: str | None
    label: str
    canonical_unit: str | None
    status: str
    is_approved: bool
    has_evidence: bool
    exceptions_clear: bool
    lineage_intact: bool
    defects: list[str]


class EntitySummaryOut(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    total_core_assigned: int
    approved: int
    completion_pct: float


class ReadinessResponse(BaseModel):
    period_id: str
    period_label: str
    period_locked: bool
    overall_status: str
    score_percent: float
    total_core_indicators: int
    ready_indicators: int
    approved_indicators: int
    evidence_attached: int
    blocking_exceptions: int
    incomplete_lineage: int
    indicators: list[IndicatorReadinessOut]
    entity_summaries: list[EntitySummaryOut]


@router.get("/readiness", response_model=ReadinessResponse)
def get_assurance_readiness(
    period_id: uuid.UUID = Query(...),
    entity_id: uuid.UUID | None = Query(default=None),
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> ReadinessResponse:
    if entity_id and user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER, UserRole.ASSESSOR):
        if entity_id not in scoped_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Entity outside your authorized scope",
            )

    try:
        data = service.compute_readiness(db, period_id=period_id, entity_id=entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return ReadinessResponse(**data)


@router.get("/export")
def export_assurance_csv(
    period_id: uuid.UUID = Query(...),
    entity_id: uuid.UUID | None = Query(default=None),
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
):
    if entity_id and user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER, UserRole.ASSESSOR):
        if entity_id not in scoped_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Entity outside your authorized scope",
            )

    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reporting period not found")

    try:
        readiness = service.compute_readiness(db, period_id=period_id, entity_id=entity_id)
        csv_text = service.export_readiness_csv(readiness)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    filename = f"assurance_readiness_{period.label}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
