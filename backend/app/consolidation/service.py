"""Bottom-up, hierarchy-aware consolidation engine (spec §13).

Semantics:
- SUM: absolute quantities summed over direct children.
- RATIO_RECALCULATION: ALWAYS sum(numerator)/sum(denominator) over children —
  percentages/intensities are NEVER averaged directly.
- WEIGHTED_AVERAGE: ratio recalculation when numerator/denominator are defined,
  otherwise a simple mean of child contributions (documented fallback).
- DERIVED_METRIC: the entity's own calculated MetricValue.
- DIRECT_VALUE: the entity's own approved value.

Inputs are APPROVED or LOCKED MetricValues only. Children without approved
values make the parent trace INCOMPLETE (recorded, never hidden). When a child
changes after consolidation, ancestor traces are marked STALE and recomputed
on demand. Every result writes a consolidation_trace with contributing value
ids, so any consolidated number can be decomposed.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_EVEN, getcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.models import (
    AppUser,
    Assignment,
    ConsolidationTrace,
    Entity,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
)
from app.models.enums import AssignmentStatus, AuditAction, MetricValueStatus

getcontext().prec = 28

QUANT = Decimal("0.00000001")

APPROVED_STATUSES = (MetricValueStatus.APPROVED, MetricValueStatus.LOCKED)


class ConsolidationError(Exception):
    pass


def _metric(db: Session, framework_version_id: uuid.UUID, code: str) -> MetricDefinition | None:
    return db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == framework_version_id,
            MetricDefinition.metric_code == code,
        )
    )


def _children(db: Session, entity_id: uuid.UUID) -> list[Entity]:
    return list(
        db.scalars(
            select(Entity).where(
                Entity.parent_id == entity_id, Entity.is_active.is_(True)
            )
        ).all()
    )


def _own_approved_value(
    db: Session, entity_id: uuid.UUID, period_id: uuid.UUID, code: str
) -> MetricValue | None:
    return db.scalar(
        select(MetricValue)
        .join(Assignment, MetricValue.assignment_id == Assignment.id)
        .where(
            Assignment.entity_id == entity_id,
            Assignment.period_id == period_id,
            Assignment.metric_code == code,
            MetricValue.status.in_(APPROVED_STATUSES),
        )
        .order_by(MetricValue.version.desc())
        .limit(1)
    )


def _period_scope(db: Session, period_id: uuid.UUID) -> tuple[ReportingPeriod, list[Entity]]:
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise ConsolidationError("Reporting period not found")
    entities = list(db.scalars(select(Entity).where(Entity.is_active.is_(True))).all())
    return period, entities


class _Consolidator:
    def __init__(self, db: Session, period: ReportingPeriod, actor: AppUser | None):
        self.db = db
        self.period = period
        self.actor = actor
        self._value_cache: dict[tuple[uuid.UUID, str], tuple[Decimal, str, list[dict]] | None] = {}
        self.failures: list[dict] = []

    def value_for(
        self, entity_id: uuid.UUID, code: str
    ) -> tuple[Decimal, str, list[dict]] | None:
        """Consolidated (value, unit, contributions) for entity+metric code.
        Contributions is a list of {entity_id, value_id, value, unit}."""
        key = (entity_id, code)
        if key in self._value_cache:
            return self._value_cache[key]
        self._value_cache[key] = None  # cycle guard
        result = self._compute(entity_id, code)
        self._value_cache[key] = result
        return result

    def _compute(self, entity_id: uuid.UUID, code: str) -> tuple[Decimal, str, list[dict]] | None:
        db = self.db
        metric = _metric(db, self.period.framework_version_id, code)
        if metric is None:
            return None
        semantics = metric.aggregation_semantics

        if semantics.value in ("DERIVED_METRIC", "DIRECT_VALUE"):
            own = _own_approved_value(db, entity_id, self.period.id, code)
            if own is None or own.normalized_value is None:
                return None
            unit = own.normalized_unit or metric.canonical_unit or ""
            contrib = [{
                "entity_id": str(entity_id), "value_id": str(own.id),
                "value": float(own.normalized_value), "unit": unit,
            }]
            return own.normalized_value, unit, contrib

        children = _children(db, entity_id)
        if not children:
            # leaves contribute their own approved value (if any)
            own = _own_approved_value(db, entity_id, self.period.id, code)
            if own is None or own.normalized_value is None:
                return None
            unit = own.normalized_unit or metric.canonical_unit or ""
            contrib = [{
                "entity_id": str(entity_id), "value_id": str(own.id),
                "value": float(own.normalized_value), "unit": unit,
            }]
            return own.normalized_value, unit, contrib

        if semantics == _semantics("RATIO_RECALCULATION"):
            num_code = metric.ratio_numerator_code
            den_code = metric.ratio_denominator_code
            if not num_code or not den_code:
                raise ConsolidationError(
                    f"{code} is RATIO_RECALCULATION without numerator/denominator"
                )
            num = self.value_for(entity_id, num_code)
            den = self.value_for(entity_id, den_code)
            if num is None or den is None:
                return None
            if den[0] == 0:
                raise ConsolidationError(
                    f"Zero denominator while consolidating {code} "
                    f"({num_code}={num[0]}, {den_code}=0)"
                )
            contributions = [
                {"entity_id": c["entity_id"], "value_id": c["value_id"],
                 "value": c["value"], "unit": c["unit"], "component": part}
                for part, series in (("numerator", num), ("denominator", den))
                for c in series[2]
            ]
            result = (num[0] / den[0] * _scale(metric)).quantize(QUANT, ROUND_HALF_EVEN)
            return result, metric.canonical_unit or "", contributions

        if semantics == _semantics("SUM"):
            total = Decimal("0")
            unit = metric.canonical_unit or ""
            contributions: list[dict] = []
            for child in children:
                child_result = self.value_for(child.id, code)
                if child_result is None:
                    continue
                total += child_result[0]
                contributions.extend({
                    "entity_id": c["entity_id"], "value_id": c["value_id"],
                    "value": c["value"], "unit": c["unit"],
                } for c in child_result[2])
            return total.quantize(QUANT, ROUND_HALF_EVEN), unit, contributions

        if semantics == _semantics("WEIGHTED_AVERAGE"):
            # preferred: ratio recalculation when num/den exist; fallback: mean
            if metric.ratio_numerator_code and metric.ratio_denominator_code:
                num = self.value_for(entity_id, metric.ratio_numerator_code)
                den = self.value_for(entity_id, metric.ratio_denominator_code)
                if num is None or den is None:
                    return None
                if den[0] == 0:
                    raise ConsolidationError(
                        f"Zero denominator while consolidating {code}"
                    )
                return ((num[0] / den[0]) * _scale(metric)).quantize(QUANT, ROUND_HALF_EVEN), \
                    metric.canonical_unit or "", []
            values: list[Decimal] = []
            contributions = []
            for child in children:
                child_result = self.value_for(child.id, code)
                if child_result is None:
                    continue
                values.append(child_result[0])
                contributions.extend({
                    "entity_id": c["entity_id"], "value_id": c["value_id"],
                    "value": c["value"], "unit": c["unit"],
                } for c in child_result[2])
            if not values:
                return None
            mean = (sum(values) / len(values)).quantize(QUANT, ROUND_HALF_EVEN)
            return mean, metric.canonical_unit or "", contributions

        raise ConsolidationError(f"Unsupported aggregation semantics {semantics}")


def _semantics(name: str):
    from app.models.enums import AggregationSemantics

    return AggregationSemantics(name)


def _scale(metric: MetricDefinition) -> Decimal:
    """Ratio metrics expressed as percent are scaled x100; unit ratios are x1."""
    if metric.unit_family == "percent" or metric.canonical_unit == "percent":
        return Decimal("100")
    return Decimal("1")


def consolidate(
    db: Session,
    entity_id: uuid.UUID,
    metric_code: str,
    period_id: uuid.UUID,
    actor: AppUser | None = None,
    request_id: str | None = None,
) -> ConsolidationTrace:
    """Compute (bottom-up) and persist the consolidation trace for one
    entity+metric+period. Never crashes: zero denominators and other errors
    raise ConsolidationError for the caller to report."""
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise ConsolidationError("Reporting period not found")
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise ConsolidationError("Entity not found")

    consolidator = _Consolidator(db, period, actor)
    result = consolidator.value_for(entity_id, metric_code)
    if result is None:
        raise ConsolidationError(
            f"No approved contributions available to consolidate {metric_code} "
            f"for this entity in this period"
        )
    value, unit, contributions = result

    trace = db.scalar(
        select(ConsolidationTrace).where(
            ConsolidationTrace.entity_id == entity_id,
            ConsolidationTrace.metric_code == metric_code,
            ConsolidationTrace.period_id == period_id,
        )
    )
    if trace is None:
        trace = ConsolidationTrace(
            entity_id=entity_id, metric_code=metric_code, period_id=period_id,
        )
        db.add(trace)
    trace.value_id = None  # consolidated numbers are traces, not MetricValues
    trace.computed_value = value
    trace.unit = unit
    trace.contributing_value_ids = [c["value_id"] for c in contributions]
    trace.aggregation_semantics = _metric(
        db, period.framework_version_id, metric_code
    ).aggregation_semantics.value
    trace.is_stale = False
    trace.stale_reason = None
    trace.computed_at = datetime.now(UTC)
    db.flush()

    record(
        db, action=AuditAction.UPDATED, object_type="consolidation_trace",
        object_id=trace.id, actor_id=actor.id if actor else None,
        actor_label=actor.email if actor else "consolidation-engine",
        entity_id=entity_id, metric_code=metric_code,
        new_value={"value": str(value), "unit": unit,
                   "contributors": len(contributions)},
        reason="consolidation computed",
        request_id=request_id,
    )
    return trace


def mark_stale_upstream(
    db: Session,
    entity_id: uuid.UUID,
    metric_code: str,
    period_id: uuid.UUID,
) -> int:
    """When a child's approved data changes, all ancestor traces become STALE."""
    marked = 0
    current: uuid.UUID | None = entity_id
    seen: set[uuid.UUID] = set()
    while current is not None and current not in seen:
        seen.add(current)
        traces = list(
            db.scalars(
                select(ConsolidationTrace).where(
                    ConsolidationTrace.entity_id == current,
                    ConsolidationTrace.metric_code == metric_code,
                    ConsolidationTrace.period_id == period_id,
                    ConsolidationTrace.is_stale.is_(False),
                )
            ).all()
        )
        for trace in traces:
            trace.is_stale = True
            trace.stale_reason = "child data changed after consolidation; recomputation required"
            marked += 1
        row = db.execute(
            select(Entity.parent_id).where(Entity.id == current)
        ).scalar()
        current = row
    db.flush()
    return marked


def mark_entity_traces_stale(db: Session, entity_id: uuid.UUID) -> int:
    """Structure change: every trace of the entity (all metrics/periods) is stale."""
    traces = list(
        db.scalars(
            select(ConsolidationTrace).where(
                ConsolidationTrace.entity_id == entity_id,
                ConsolidationTrace.is_stale.is_(False),
            )
        ).all()
    )
    for trace in traces:
        trace.is_stale = True
        trace.stale_reason = "entity structure changed after consolidation; recomputation required"
    db.flush()
    return len(traces)


def run_consolidation(
    db: Session,
    period_id: uuid.UUID,
    metric_codes: list[str] | None = None,
    actor: AppUser | None = None,
    request_id: str | None = None,
) -> dict:
    """Consolidate every active metric for every entity, bottom-up (leaves
    first). Failures are reported per entity+metric, never silent."""
    period, entities = _period_scope(db, period_id)
    if metric_codes is None:
        metric_codes = list(
            db.scalars(
                select(MetricDefinition.metric_code).where(
                    MetricDefinition.framework_version_id == period.framework_version_id
                )
            ).all()
        )

    # leaves first: order by depth (parent chains resolved in Python)
    by_id = {e.id: e for e in entities}
    depth: dict[uuid.UUID, int] = {}

    def _depth(entity_id: uuid.UUID) -> int:
        if entity_id in depth:
            return depth[entity_id]
        parent = by_id[entity_id].parent_id
        depth[entity_id] = 0 if parent is None or parent not in by_id else _depth(parent) + 1
        return depth[entity_id]

    ordered = sorted(entities, key=lambda e: _depth(e.id))

    consolidated = 0
    failures: list[dict] = []
    for entity in ordered:
        for code in metric_codes:
            try:
                consolidate(db, entity.id, code, period_id, actor=actor, request_id=request_id)
                consolidated += 1
            except ConsolidationError as exc:
                failures.append({
                    "entity_id": str(entity.id),
                    "entity_name": entity.name,
                    "metric_code": code,
                    "error": str(exc),
                })
    return {"consolidated": consolidated, "failures": failures, "metrics": len(metric_codes)}
