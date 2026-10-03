"""Multi-year trends (spec §20). Honors metric_lineage: values are compared
across periods only where a continuity mapping exists between framework
versions — otherwise the year is reported as a GAP, never silently compared
against a differently-defined metric."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.db.session import get_db
from app.models import (
    AppUser,
    ConsolidationTrace,
    Entity,
    FrameworkVersion,
    MetricDefinition,
    MetricLineage,
    ReportingPeriod,
)
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


class TrendPoint(BaseModel):
    period_label: str
    framework_version: str
    value: float | None
    unit: str | None
    continuity: str  # direct | remapped | gap
    note: str | None = None


class TrendResponse(BaseModel):
    metric_code: str
    label: str
    unit: str | None
    points: list[TrendPoint]


def _trace_value(db: Session, entity_id: uuid.UUID, code: str, period_id: uuid.UUID):
    trace = db.scalar(
        select(ConsolidationTrace).where(
            ConsolidationTrace.entity_id == entity_id,
            ConsolidationTrace.metric_code == code,
            ConsolidationTrace.period_id == period_id,
        )
    )
    if trace is None or trace.computed_value is None:
        return None, None
    return float(trace.computed_value), trace.unit


def _resolve_code_for_version(
    db: Session, requested_code: str, base_fv_id: uuid.UUID, target_fv_id: uuid.UUID
) -> tuple[str | None, str, str | None]:
    """Resolve the requested metric's code in another framework version via
    metric_lineage. Returns (code_or_None, continuity, note)."""
    if target_fv_id == base_fv_id:
        exists = db.scalar(
            select(MetricDefinition.id).where(
                MetricDefinition.framework_version_id == target_fv_id,
                MetricDefinition.metric_code == requested_code,
            )
        )
        return (requested_code, "direct", None) if exists else (None, "gap", "metric absent in this version")
    forward = db.scalar(
        select(MetricLineage).where(
            MetricLineage.from_framework_version_id == base_fv_id,
            MetricLineage.from_metric_code == requested_code,
            MetricLineage.to_framework_version_id == target_fv_id,
        )
    )
    if forward is not None:
        note = None
        if forward.mapping_type in ("REDEFINED", "SPLIT"):
            note = f"definition {forward.mapping_type.lower()} between versions; compare with care"
        return forward.to_metric_code, "remapped", note
    backward = db.scalar(
        select(MetricLineage).where(
            MetricLineage.to_framework_version_id == base_fv_id,
            MetricLineage.to_metric_code == requested_code,
            MetricLineage.from_framework_version_id == target_fv_id,
        )
    )
    if backward is not None:
        return backward.from_metric_code, "remapped", "resolved via reverse lineage mapping"
    return None, "gap", "no continuity mapping between framework versions"


@router.get("/{metric_code}", response_model=TrendResponse)
def trend(
    metric_code: str,
    entity_id: uuid.UUID = Query(default=None),
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> TrendResponse:
    if entity_id is None:
        group = db.scalar(select(Entity).where(Entity.name == "MEIL Group"))
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No group entity")
        entity_id = group.id
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER) and entity_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Entity outside your authorized scope")

    periods = list(
        db.scalars(select(ReportingPeriod).order_by(ReportingPeriod.start_date)).all()
    )
    if not periods:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No reporting periods")
    base_fv = periods[-1].framework_version_id
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == base_fv,
            MetricDefinition.metric_code == metric_code,
        )
    )
    if metric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Metric {metric_code!r} not found in the current framework version")

    points: list[TrendPoint] = []
    for period in periods:
        code, continuity, note = _resolve_code_for_version(
            db, metric_code, base_fv, period.framework_version_id
        )
        value, unit = (None, None)
        if code is not None:
            value, unit = _trace_value(db, entity_id, code, period.id)
        if value is None and continuity != "gap":
            continuity = "gap"
            note = "no consolidated value for this period yet"
        points.append(TrendPoint(
            period_label=period.label,
            framework_version=db.get(FrameworkVersion, period.framework_version_id).version_code,
            value=value,
            unit=unit,
            continuity=continuity,
            note=note,
        ))
    return TrendResponse(
        metric_code=metric_code, label=metric.label, unit=metric.canonical_unit, points=points
    )
