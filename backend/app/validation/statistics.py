"""Statistical anomaly detection across peer sites (research §5.9, §8.2, §8.3).

Two layers on top of the rule-based engine, exactly as the research
recommends: threshold rules first, statistical checks as the second layer
once peer history exists.

- IQR (robust): flag x < Q1 - 1.5*IQR or x > Q3 + 1.5*IQR across peer sites
  reporting the same metric in the same period.
- Z-score: flag |x - mu| / sigma > 2 across peers (skipped for tiny samples
  or zero variance — the misuse-cases the research calls out).

Both produce WARNING exceptions attributed to versioned validation rules, so
they flow through the same explain/resolve lifecycle as deterministic rules.
"""
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.models import (
    Assignment,
    Entity,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
    ValidationException,
    ValidationRule,
)
from app.models.enums import (
    AuditAction,
    MetricValueStatus,
    ValidationExceptionStatus,
)

IQR_MULTIPLIER = 1.5
ZSCORE_THRESHOLD = 2.0
MIN_PEERS = 4


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile on an ascending list."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = (n - 1) * q
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def iqr_bounds(values: list[float]) -> tuple[float, float, float, float, float] | None:
    """Returns (q1, q3, iqr, lower, upper) or None when not meaningful."""
    if len(values) < MIN_PEERS:
        return None
    s = sorted(values)
    q1 = _quantile(s, 0.25)
    q3 = _quantile(s, 0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    return q1, q3, iqr, q1 - IQR_MULTIPLIER * iqr, q3 + IQR_MULTIPLIER * iqr


def zscore(value: float, peers: list[float]) -> float | None:
    """z = (x - mu) / sigma over the peer set including the value itself."""
    if len(peers) < MIN_PEERS:
        return None
    mu = sum(peers) / len(peers)
    var = sum((p - mu) ** 2 for p in peers) / len(peers)
    sigma = var ** 0.5
    if sigma == 0:
        return None
    return (value - mu) / sigma


def _approved_peer_values(
    db: Session, period_id: uuid.UUID, code: str
) -> list[tuple[Entity, MetricValue, float]]:
    rows = db.execute(
        select(Entity, MetricValue)
        .join(Assignment, MetricValue.assignment_id == Assignment.id)
        .join(Entity, Assignment.entity_id == Entity.id)
        .where(
            Assignment.period_id == period_id,
            Assignment.metric_code == code,
            Assignment.entity_id == Assignment.entity_id,  # no-op, keeps join explicit
            MetricValue.status.in_([MetricValueStatus.APPROVED, MetricValueStatus.LOCKED]),
            Entity.entity_type.in_(["PLANT", "PROJECT"]),
        )
        .order_by(MetricValue.version.desc())
    ).all()
    latest: dict[uuid.UUID, tuple[Entity, MetricValue, float]] = {}
    for entity, value in rows:
        if entity.id in latest or value.normalized_value is None:
            continue
        latest[entity.id] = (entity, value, float(value.normalized_value))
    return list(latest.values())


def _rule(db: Session, framework_version_id: uuid.UUID, code: str) -> ValidationRule | None:
    return db.scalar(
        select(ValidationRule).where(
            ValidationRule.framework_version_id == framework_version_id,
            ValidationRule.rule_code == code,
            ValidationRule.version == 1,
        )
    )


def _persist(
    db: Session,
    rule: ValidationRule,
    period_id: uuid.UUID,
    entity_id: uuid.UUID,
    metric_code: str,
    message: str,
    observed: float,
    actor_id: uuid.UUID | None,
    actor_label: str,
) -> bool:
    exists = db.scalar(
        select(ValidationException.id).where(
            ValidationException.rule_id == rule.id,
            ValidationException.entity_id == entity_id,
            ValidationException.period_id == period_id,
            ValidationException.status != ValidationExceptionStatus.RESOLVED,
        )
    )
    if exists:
        return False
    exception = ValidationException(
        rule_id=rule.id, rule_code=rule.rule_code, rule_version=rule.version,
        severity=rule.severity, message=message,
        entity_id=entity_id, metric_code=metric_code, period_id=period_id,
        observed_value=Decimal(str(round(observed, 6))),
        status=ValidationExceptionStatus.OPEN,
    )
    db.add(exception)
    db.flush()
    record(
        db, action=AuditAction.EXCEPTION_RAISED, object_type="validation_exception",
        object_id=exception.id, actor_id=actor_id, actor_label=actor_label,
        entity_id=entity_id, metric_code=metric_code,
        new_value={"rule": rule.rule_code, "statistical": True, "message": message},
    )
    return True


def run_statistical_sweep(
    db: Session,
    period_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    actor_label: str = "system",
) -> dict:
    """Cross-site IQR + z-score sweep for the period. Deterministic and
    explainable; skipped where peer samples are too small (per §8.2)."""
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        return {"checked": 0, "raised": 0}
    metrics = list(
        db.scalars(
            select(MetricDefinition).where(
                MetricDefinition.framework_version_id == period.framework_version_id,
                MetricDefinition.data_type == "numeric",
            )
        ).all()
    )
    iqr_rule = _rule(db, period.framework_version_id, "VR-IQR-PEER")
    z_rule = _rule(db, period.framework_version_id, "VR-ZSCORE-PEER")

    checked = 0
    raised = 0
    for metric in metrics:
        peers = _approved_peer_values(db, period.id, metric.metric_code)
        if len(peers) < MIN_PEERS:
            continue
        values = [v for _, _, v in peers]
        checked += 1
        bounds = iqr_bounds(values)
        if bounds is not None and iqr_rule is not None:
            q1, q3, _iqr, lower, upper = bounds
            for entity, _value, v in peers:
                if v < lower or v > upper:
                    side = "above" if v > upper else "below"
                    raised += int(_persist(
                        db, iqr_rule, period.id, entity.id, metric.metric_code,
                        message=(
                            f"{metric.label} for {entity.name} is {side} the peer "
                            f"interquartile range (value {v:g}, peer Q1–Q3 "
                            f"{q1:g}–{q3:g}, bounds {lower:g}–{upper:g})"
                        ),
                        observed=v, actor_id=actor_id, actor_label=actor_label,
                    ))
        if z_rule is not None:
            for entity, _value, v in peers:
                z = zscore(v, values)
                if z is not None and abs(z) > ZSCORE_THRESHOLD:
                    raised += int(_persist(
                        db, z_rule, period.id, entity.id, metric.metric_code,
                        message=(
                            f"{metric.label} for {entity.name} is a cross-site "
                            f"statistical outlier (z = {z:+.2f}, peer mean "
                            f"{sum(values) / len(values):.2f})"
                        ),
                        observed=v, actor_id=actor_id, actor_label=actor_label,
                    ))
    return {"checked": checked, "raised": raised}
