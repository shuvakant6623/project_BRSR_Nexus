"""Consolidation API: read traces, trigger recomputation."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.consolidation import service
from app.db.session import get_db
from app.logging import request_id_var
from app.models import (
    AppUser,
    Assignment,
    ConsolidationTrace,
    Entity,
    MetricValue,
    ReportingPeriod,
)
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1/consolidation", tags=["consolidation"])


class RecomputeRequest(BaseModel):
    period_id: uuid.UUID
    metric_code: str | None = None


class ContributionOut(BaseModel):
    entity_id: str
    entity_name: str
    value_id: str
    value: float
    unit: str
    component: str | None = None


class TraceOut(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    metric_code: str
    period_id: uuid.UUID
    period_label: str
    computed_value: float | None
    unit: str | None
    aggregation_semantics: str | None
    is_stale: bool
    stale_reason: str | None
    computed_at: str | None
    contributing_value_count: int
    contributions: list[ContributionOut]


def _load_trace(db: Session, entity_id: uuid.UUID, metric_code: str, period_id: uuid.UUID) -> ConsolidationTrace:
    trace = db.scalar(
        select(ConsolidationTrace).where(
            ConsolidationTrace.entity_id == entity_id,
            ConsolidationTrace.metric_code == metric_code,
            ConsolidationTrace.period_id == period_id,
        )
    )
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No consolidation trace for this entity/metric/period; run consolidation first")
    return trace


def _trace_out(db: Session, trace: ConsolidationTrace) -> TraceOut:
    entity = db.get(Entity, trace.entity_id)
    period = db.get(ReportingPeriod, trace.period_id)
    contributions: list[ContributionOut] = []
    # decompose the trace back to its contributing MetricValues
    value_ids = trace.contributing_value_ids or []
    values = list(
        db.scalars(
            select(MetricValue).where(MetricValue.id.in_(value_ids))
        ).all()
    ) if value_ids else []
    for value in values:
        assignment = db.get(Assignment, value.assignment_id)
        contrib_entity = db.get(Entity, assignment.entity_id) if assignment else None
        contributions.append(
            ContributionOut(
                entity_id=str(assignment.entity_id) if assignment else "?",
                entity_name=contrib_entity.name if contrib_entity else "?",
                value_id=str(value.id),
                value=float(value.normalized_value) if value.normalized_value is not None else 0.0,
                unit=value.normalized_unit or "",
            )
        )
    return TraceOut(
        entity_id=trace.entity_id,
        entity_name=entity.name if entity else "?",
        metric_code=trace.metric_code,
        period_id=trace.period_id,
        period_label=period.label if period else "?",
        computed_value=float(trace.computed_value) if trace.computed_value is not None else None,
        unit=trace.unit,
        aggregation_semantics=trace.aggregation_semantics,
        is_stale=trace.is_stale,
        stale_reason=trace.stale_reason,
        computed_at=trace.computed_at.isoformat() if trace.computed_at else None,
        contributing_value_count=len(value_ids),
        contributions=contributions,
    )


@router.get("/{entity_id}/{metric_code}/{period_id}", response_model=TraceOut)
def get_trace(
    entity_id: uuid.UUID,
    metric_code: str,
    period_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> TraceOut:
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER) and entity_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Entity outside your authorized scope")
    return _trace_out(db, _load_trace(db, entity_id, metric_code, period_id))


@router.post("/recompute")
def recompute(
    body: RecomputeRequest,
    request: Request,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only ESG managers and admins may trigger consolidation")
    metric_codes = [body.metric_code] if body.metric_code else None
    result = service.run_consolidation(
        db, body.period_id, metric_codes=metric_codes, actor=user,
        request_id=request_id_var.get(),
    )
    db.commit()
    return {"status": "completed", **result}
