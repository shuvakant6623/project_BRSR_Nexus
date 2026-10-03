"""Lineage read model (research §10 — "show me where this number came from").

Assembles, from existing tables only, the full provenance chain for any
consolidated or leaf figure: contributors, raw→normalized values, formula
version + resolved inputs, evidence files with hashes, uploader, submission
and approval timestamps, audit history, and staleness.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.db.session import get_db
from app.models import (
    AppUser,
    Assignment,
    AuditEvent,
    ConsolidationTrace,
    Entity,
    Evidence,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
    UserEntityScope,
)
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1/lineage", tags=["lineage"])


class EvidenceNode(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    uploaded_at: object


class AuditNode(BaseModel):
    action: str
    actor: str
    at: object
    reason: str | None


class ChainNode(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    entity_type: str
    metric_code: str
    value_id: uuid.UUID
    version: int
    raw_value: float | None
    raw_unit: str | None
    normalized_value: float | None
    normalized_unit: str | None
    is_calculated: bool
    status: str
    uploader: str | None
    submitted_at: object | None
    approved_at: object | None
    evidence: list[EvidenceNode]
    audit: list[AuditNode]


class LineageResponse(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    metric_code: str
    metric_label: str
    unit: str | None
    period_id: uuid.UUID
    period_label: str
    kind: str  # consolidated | leaf
    value: float | None
    aggregation_semantics: str | None
    is_stale: bool
    stale_reason: str | None
    computed_at: object | None
    formula: dict | None
    chain: list[ChainNode]
    audit_count: int


def _audit_for_value(db: Session, value_id: uuid.UUID) -> list[AuditNode]:
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.object_type == "metric_value", AuditEvent.object_id == str(value_id))
            .order_by(AuditEvent.created_at)
        ).all()
    )
    return [
        AuditNode(
            action=e.action.value, actor=e.actor_label, at=e.created_at, reason=e.reason
        )
        for e in events
    ]


def _chain_node(db: Session, value: MetricValue) -> ChainNode:
    assignment = db.get(Assignment, value.assignment_id)
    entity = db.get(Entity, assignment.entity_id)
    uploader = db.get(AppUser, value.created_by)
    evidence_rows = list(
        db.scalars(
            select(Evidence).where(
                Evidence.metric_value_id == value.id, Evidence.is_deleted.is_(False)
            )
        ).all()
    )
    approval = next(
        (
            e for e in _audit_for_value(db, value.id)
            if e.action in ("APPROVED", "SUBMITTED")
        ),
        None,
    )
    return ChainNode(
        entity_id=entity.id if entity else assignment.entity_id,
        entity_name=entity.name if entity else "?",
        entity_type=entity.entity_type.value if entity else "?",
        metric_code=assignment.metric_code,
        value_id=value.id,
        version=value.version,
        raw_value=float(value.raw_value) if value.raw_value is not None else None,
        raw_unit=value.raw_unit,
        normalized_value=float(value.normalized_value) if value.normalized_value is not None else None,
        normalized_unit=value.normalized_unit,
        is_calculated=value.is_calculated,
        status=value.status.value,
        uploader=uploader.email if uploader else None,
        submitted_at=value.submitted_at,
        approved_at=approval.at if approval else None,
        evidence=[
            EvidenceNode(
                id=ev.id, filename=ev.original_filename, mime_type=ev.mime_type,
                size_bytes=ev.size_bytes, sha256=ev.sha256_hash,
                uploaded_by=str(ev.uploaded_by), uploaded_at=ev.uploaded_at,
            )
            for ev in evidence_rows
        ],
        audit=_audit_for_value(db, value.id),
    )


@router.get("/{entity_id}/{metric_code}/{period_id}", response_model=LineageResponse)
def lineage(
    entity_id: uuid.UUID,
    metric_code: str,
    period_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> LineageResponse:
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER) and entity_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Entity outside your authorized scope")
    entity = db.get(Entity, entity_id)
    period = db.get(ReportingPeriod, period_id)
    if entity is None or period is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity or period not found")
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == period.framework_version_id,
            MetricDefinition.metric_code == metric_code,
        )
    )
    if metric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found in this period's framework")

    trace = db.scalar(
        select(ConsolidationTrace).where(
            ConsolidationTrace.entity_id == entity_id,
            ConsolidationTrace.metric_code == metric_code,
            ConsolidationTrace.period_id == period_id,
        )
    )

    formula = None
    chain: list[ChainNode] = []
    audit_count = 0

    if trace is not None and trace.contributing_value_ids:
        values = list(
            db.scalars(
                select(MetricValue).where(MetricValue.id.in_(trace.contributing_value_ids))
            ).all()
        )
        chain = [_chain_node(db, v) for v in values]
        chain.sort(key=lambda n: n.entity_name)
    else:
        # leaf: the entity's own latest value
        value = db.execute(
            select(MetricValue)
            .join(Assignment, MetricValue.assignment_id == Assignment.id)
            .where(
                Assignment.entity_id == entity_id,
                Assignment.period_id == period_id,
                Assignment.metric_code == metric_code,
            )
            .order_by(MetricValue.version.desc())
            .limit(1)
        ).scalar()
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No value or consolidation trace exists for this figure yet",
            )
        chain = [_chain_node(db, value)]

    # formula metadata if any chain node is calculated
    calculated = next((n for n in chain if n.is_calculated), None)
    if calculated is not None:
        from app.models import FormulaDefinition, FormulaVersion

        mv = db.get(MetricValue, calculated.value_id)
        if mv is not None and mv.formula_id is not None:
            definition = db.get(FormulaDefinition, mv.formula_id)
            fv = db.scalar(
                select(FormulaVersion).where(
                    FormulaVersion.formula_definition_id == mv.formula_id,
                    FormulaVersion.version == (mv.formula_version or 1),
                )
            )
            if definition is not None and fv is not None:
                formula = {
                    "code": definition.code,
                    "name": definition.name,
                    "version": fv.version,
                    "expression": fv.expression,
                    "input_metric_codes": fv.input_metric_codes,
                    "constants": fv.constants,
                    "resolved_inputs": mv.formula_inputs or {},
                }

    audit_count = sum(len(n.audit) for n in chain)
    value = (
        float(trace.computed_value)
        if trace is not None and trace.computed_value is not None
        else (chain[0].normalized_value if chain else None)
    )
    return LineageResponse(
        entity_id=entity_id,
        entity_name=entity.name,
        metric_code=metric_code,
        metric_label=metric.label,
        unit=metric.canonical_unit,
        period_id=period_id,
        period_label=period.label,
        kind="consolidated" if trace is not None and trace.contributing_value_ids else "leaf",
        value=value,
        aggregation_semantics=trace.aggregation_semantics if trace else metric.aggregation_semantics.value,
        is_stale=trace.is_stale if trace else False,
        stale_reason=trace.stale_reason if trace else None,
        computed_at=trace.computed_at if trace else None,
        formula=formula,
        chain=chain,
        audit_count=audit_count,
    )
