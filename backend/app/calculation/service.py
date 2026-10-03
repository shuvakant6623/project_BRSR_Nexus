"""Calculation service: computes derived MetricValues from versioned formulas.

Every calculated value stores formula_id, formula_version and the resolved
input snapshot (formula_inputs) so the same inputs + same formula version
always reproduce the same result. Missing inputs raise — never silently zero.
"""
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.calculation.evaluator import CalculationError, evaluate
from app.models import (
    AppUser,
    Assignment,
    FormulaDefinition,
    FormulaVersion,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
)
from app.models.enums import AssignmentStatus, AuditAction, MetricValueStatus

EDITABLE_STATUSES = {
    AssignmentStatus.NOT_STARTED,
    AssignmentStatus.IN_PROGRESS,
    AssignmentStatus.NEEDS_CORRECTION,
    AssignmentStatus.REJECTED,
}


class MissingInputError(CalculationError):
    pass


def _input_value(db: Session, entity_id: uuid.UUID, period_id: uuid.UUID, code: str) -> Decimal | None:
    """Latest non-null normalized value for entity+period+metric code."""
    row = db.execute(
        select(MetricValue)
        .join(Assignment, MetricValue.assignment_id == Assignment.id)
        .where(
            Assignment.entity_id == entity_id,
            Assignment.period_id == period_id,
            Assignment.metric_code == code,
        )
        .order_by(MetricValue.version.desc())
    ).scalars().all()
    for value in row:
        if value.normalized_value is not None:
            return value.normalized_value
    return None


def _assignment_for(db: Session, entity_id: uuid.UUID, period_id: uuid.UUID, code: str) -> Assignment | None:
    return db.scalar(
        select(Assignment).where(
            Assignment.entity_id == entity_id,
            Assignment.period_id == period_id,
            Assignment.metric_code == code,
        )
    )


def compute_assignment(
    db: Session,
    assignment: Assignment,
    actor: AppUser | None = None,
    request_id: str | None = None,
) -> MetricValue | None:
    """(Re)compute the latest version of a derived metric assignment.

    Returns the new MetricValue, or None when recompute was skipped because
    the assignment is beyond edit (SUBMITTED/APPROVED — its data is frozen;
    the ESG manager recomputes via the run endpoint during review cycles).
    """
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == assignment.framework_version_id,
            MetricDefinition.metric_code == assignment.metric_code,
        )
    )
    if metric is None or metric.calculation_rule_id is None:
        return None
    period = db.get(ReportingPeriod, assignment.period_id)
    if period is None or period.locked:
        return None
    if assignment.status not in EDITABLE_STATUSES:
        return None

    definition = db.get(FormulaDefinition, metric.calculation_rule_id)
    if definition is None:
        raise CalculationError(f"Formula definition missing for {assignment.metric_code}")
    formula_version = db.scalar(
        select(FormulaVersion)
        .where(FormulaVersion.formula_definition_id == definition.id)
        .order_by(FormulaVersion.version.desc())
        .limit(1)
    )
    if formula_version is None:
        raise CalculationError(f"No formula version exists for {definition.code}")

    inputs: dict[str, Decimal] = {}
    missing: list[str] = []
    for code in formula_version.input_metric_codes:
        value = _input_value(db, assignment.entity_id, assignment.period_id, code)
        if value is None:
            missing.append(code)
        else:
            inputs[code] = value
    if missing:
        raise MissingInputError(
            f"Cannot calculate {assignment.metric_code}: missing inputs {', '.join(missing)}"
        )

    constants = {k: Decimal(str(v)) for k, v in formula_version.constants.items()}

    def resolve(name: str) -> Decimal:
        if name in inputs:
            return inputs[name]
        if name in constants:
            return constants[name]
        raise CalculationError(f"Unknown identifier {name!r} in formula {definition.code}")

    result = evaluate(formula_version.expression, resolve)

    latest = db.scalar(
        select(MetricValue)
        .where(MetricValue.assignment_id == assignment.id)
        .order_by(MetricValue.version.desc())
        .limit(1)
    )
    formula_inputs = {code: str(value) for code, value in inputs.items()}
    if (
        latest is not None
        and latest.is_calculated
        and latest.raw_value == result
        and latest.formula_version == formula_version.version
        and latest.formula_inputs == formula_inputs
    ):
        return None  # idempotent: inputs and formula unchanged

    value = MetricValue(
        assignment_id=assignment.id,
        version=(latest.version if latest else 0) + 1,
        raw_value=result,
        raw_unit=metric.canonical_unit,
        normalized_value=result,
        normalized_unit=metric.canonical_unit,
        is_calculated=True,
        formula_id=definition.id,
        formula_version=formula_version.version,
        formula_inputs=formula_inputs,
        status=MetricValueStatus.IN_PROGRESS,
        created_by=actor.id if actor else assignment.owner_user_id,
    )
    db.add(value)
    if assignment.status == AssignmentStatus.NOT_STARTED:
        assignment.status = AssignmentStatus.IN_PROGRESS
    db.flush()

    record(
        db, action=AuditAction.UPDATED, object_type="metric_value", object_id=value.id,
        actor_id=actor.id if actor else None,
        actor_label=actor.email if actor else "calculation-engine",
        entity_id=assignment.entity_id, metric_code=assignment.metric_code,
        new_value={"version": value.version, "result": str(result),
                   "formula": definition.code, "formula_version": formula_version.version},
        reason="derived metric recomputation",
        request_id=request_id,
    )
    return value


def recompute_dependents(
    db: Session,
    framework_version_id: uuid.UUID,
    entity_id: uuid.UUID,
    period_id: uuid.UUID,
    changed_metric_code: str,
    actor: AppUser | None = None,
    request_id: str | None = None,
) -> int:
    """Recompute every derived metric whose formula consumes changed_metric_code."""
    definitions = list(
        db.scalars(
            select(FormulaDefinition).where(
                FormulaDefinition.framework_version_id == framework_version_id
            )
        ).all()
    )
    dependent_codes: set[str] = set()
    for definition in definitions:
        versions = list(
            db.scalars(
                select(FormulaVersion).where(
                    FormulaVersion.formula_definition_id == definition.id
                )
            ).all()
        )
        if any(changed_metric_code in fv.input_metric_codes for fv in versions):
            dependent_codes.update(
                db.scalars(
                    select(MetricDefinition.metric_code).where(
                        MetricDefinition.framework_version_id == framework_version_id,
                        MetricDefinition.calculation_rule_id == definition.id,
                    )
                ).all()
            )
    recomputed = 0
    for code in dependent_codes:
        assignment = _assignment_for(db, entity_id, period_id, code)
        if assignment is None:
            continue
        try:
            if compute_assignment(db, assignment, actor=actor, request_id=request_id) is not None:
                recomputed += 1
        except CalculationError:
            # missing inputs etc.: the run endpoint reports these explicitly
            continue
    return recomputed


def run_calculations(
    db: Session,
    period_id: uuid.UUID,
    entity_ids: list[uuid.UUID] | None = None,
    actor: AppUser | None = None,
    request_id: str | None = None,
) -> dict:
    """Recompute every derived metric in the period (optionally per entity).

    Failures (missing inputs etc.) are reported per assignment, never silent.
    """
    stmt = (
        select(Assignment)
        .join(MetricDefinition, (MetricDefinition.framework_version_id == Assignment.framework_version_id)
              & (MetricDefinition.metric_code == Assignment.metric_code))
        .where(
            Assignment.period_id == period_id,
            MetricDefinition.calculation_rule_id.is_not(None),
        )
    )
    if entity_ids:
        stmt = stmt.where(Assignment.entity_id.in_(entity_ids))
    assignments = list(db.scalars(stmt).all())

    computed = 0
    skipped = 0
    failures: list[dict] = []
    for assignment in assignments:
        try:
            value = compute_assignment(db, assignment, actor=actor, request_id=request_id)
            if value is None:
                skipped += 1
            else:
                computed += 1
        except CalculationError as exc:
            failures.append({
                "assignment_id": str(assignment.id),
                "entity_id": str(assignment.entity_id),
                "metric_code": assignment.metric_code,
                "error": str(exc),
            })
    return {"computed": computed, "skipped": skipped, "failures": failures}
