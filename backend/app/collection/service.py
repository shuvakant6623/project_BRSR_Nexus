"""Collection domain service: assignment creation, value versioning, the
assignment state machine and review transitions.

Guards (spec §9):
- NOT_STARTED → IN_PROGRESS: owner opens/saves
- IN_PROGRESS → SUBMITTED: required structural validation passes
- SUBMITTED → UNDER_REVIEW: reviewer opens
- UNDER_REVIEW → APPROVED: no unresolved blocking exceptions
- UNDER_REVIEW → NEEDS_CORRECTION / REJECTED: review comment required
- NEEDS_CORRECTION / REJECTED → IN_PROGRESS: owner saves
- APPROVED → LOCKED: reporting period locked (system)
Every value edit creates a NEW MetricValue version; history is never mutated.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.entities.service import get_descendant_ids
from app.models import (
    AppUser,
    Assignment,
    Entity,
    FrameworkVersion,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
    ValidationException,
)
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    MetricValueStatus,
    NotificationType,
    UserRole,
    ValidationExceptionStatus,
    ValidationSeverity,
)


class CollectionError(Exception):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# assignment-level transition map
TRANSITIONS: dict[AssignmentStatus, set[AssignmentStatus]] = {
    AssignmentStatus.NOT_STARTED: {AssignmentStatus.IN_PROGRESS},
    AssignmentStatus.IN_PROGRESS: {AssignmentStatus.SUBMITTED},
    AssignmentStatus.SUBMITTED: {AssignmentStatus.UNDER_REVIEW},
    AssignmentStatus.UNDER_REVIEW: {
        AssignmentStatus.APPROVED,
        AssignmentStatus.NEEDS_CORRECTION,
        AssignmentStatus.REJECTED,
    },
    AssignmentStatus.NEEDS_CORRECTION: {AssignmentStatus.IN_PROGRESS},
    AssignmentStatus.REJECTED: {AssignmentStatus.IN_PROGRESS},
    AssignmentStatus.APPROVED: {AssignmentStatus.LOCKED},
    AssignmentStatus.LOCKED: set(),
}

VALUE_STATUS_FOR_ASSIGNMENT = {
    AssignmentStatus.IN_PROGRESS: MetricValueStatus.IN_PROGRESS,
    AssignmentStatus.SUBMITTED: MetricValueStatus.SUBMITTED,
    AssignmentStatus.UNDER_REVIEW: MetricValueStatus.UNDER_REVIEW,
    AssignmentStatus.APPROVED: MetricValueStatus.APPROVED,
    AssignmentStatus.NEEDS_CORRECTION: MetricValueStatus.NEEDS_CORRECTION,
    AssignmentStatus.REJECTED: MetricValueStatus.REJECTED,
    AssignmentStatus.LOCKED: MetricValueStatus.LOCKED,
}


def create_assignment(
    db: Session,
    *,
    metric_code: str,
    entity_id: uuid.UUID,
    period_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    created_by: AppUser,
    due_date=None,
    request_id: str | None = None,
) -> Assignment:
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise CollectionError("Reporting period not found", 404)
    if period.locked:
        raise CollectionError("Cannot assign metrics for a locked period")
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise CollectionError("Entity not found", 404)
    owner = db.get(AppUser, owner_user_id)
    if owner is None:
        raise CollectionError("Owner user not found", 404)
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == period.framework_version_id,
            MetricDefinition.metric_code == metric_code,
        )
    )
    if metric is None:
        raise CollectionError(
            f"Metric {metric_code!r} does not exist in the period's framework version"
        )
    duplicate = db.scalar(
        select(Assignment).where(
            Assignment.metric_code == metric_code,
            Assignment.entity_id == entity_id,
            Assignment.period_id == period_id,
        )
    )
    if duplicate:
        raise CollectionError("An assignment for this metric/entity/period already exists")

    assignment = Assignment(
        metric_code=metric_code,
        framework_version_id=period.framework_version_id,
        entity_id=entity_id,
        period_id=period_id,
        owner_user_id=owner_user_id,
        due_date=due_date,
        status=AssignmentStatus.NOT_STARTED,
        created_by=created_by.id,
    )
    db.add(assignment)
    db.flush()
    record(
        db, action=AuditAction.CREATED, object_type="assignment", object_id=assignment.id,
        actor_id=created_by.id, actor_label=created_by.email,
        entity_id=entity_id, metric_code=metric_code,
        new_value={"period": period.label, "owner": owner.email},
        request_id=request_id,
    )
    return assignment


def visible_assignment_ids(db: Session, user: AppUser) -> set[uuid.UUID] | None:
    """None means unrestricted (ADMIN/ESG_MANAGER)."""
    if user.role.name in ("ADMIN", "ESG_MANAGER"):
        return None
    if user.role.name == "DATA_OWNER":
        return set(
            db.scalars(select(Assignment.id).where(Assignment.owner_user_id == user.id)).all()
        )
    # REVIEWER / MANAGEMENT / ASSESSOR: assignments within scoped entity subtrees
    scoped_entities: set[uuid.UUID] = set()
    for scope in user.entity_scopes:
        scoped_entities |= get_descendant_ids(db, scope.entity_id)
    return set(
        db.scalars(select(Assignment.id).where(Assignment.entity_id.in_(scoped_entities))).all()
    )


def latest_value(db: Session, assignment_id: uuid.UUID) -> MetricValue | None:
    return db.scalar(
        select(MetricValue)
        .where(MetricValue.assignment_id == assignment_id)
        .order_by(MetricValue.version.desc())
        .limit(1)
    )


def _metric_for_assignment(db: Session, assignment: Assignment) -> MetricDefinition:
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == assignment.framework_version_id,
            MetricDefinition.metric_code == assignment.metric_code,
        )
    )
    if metric is None:
        raise CollectionError("Metric definition missing", 500)
    return metric


def _structural_validate(metric: MetricDefinition, payload: dict) -> None:
    """Basic structural checks required before SUBMIT. The full deterministic
    validation engine (cross-field, YoY, evidence) runs in the validation phase."""
    if metric.data_type.value == "numeric":
        if payload.get("raw_value") is None:
            raise CollectionError("Numeric value is required", 422)
        try:
            val = Decimal(str(payload["raw_value"]))
        except InvalidOperation:
            raise CollectionError("Value is not a valid number", 422)
        # Physical quantities can never be negative
        NON_NEGATIVE_FAMILIES = frozenset({
            "energy", "emissions", "water", "waste", "fuel_volume",
            "currency", "count", "workforce",
        })
        if metric.unit_family in NON_NEGATIVE_FAMILIES and val < 0:
            raise CollectionError(
                f"{metric.label} cannot be negative (received {val})", 422,
            )
        if metric.allowed_units and payload.get("raw_unit") not in metric.allowed_units:
            raise CollectionError(
                f"Unit {payload.get('raw_unit')!r} is not allowed for this metric "
                f"(allowed: {metric.allowed_units})",
                422,
            )
    else:
        if not payload.get("qualitative_value"):
            raise CollectionError("A response is required for this metric", 422)


def save_value(
    db: Session,
    assignment: Assignment,
    *,
    action: str,
    payload: dict,
    actor: AppUser,
    expected_last_version: int | None = None,
    request_id: str | None = None,
) -> MetricValue:
    if actor.role == UserRole.ASSESSOR:
        raise CollectionError("Assessors have read-only access and cannot edit values", 403)
    is_override = bool(payload.get("is_override", False))
    override_reason = payload.get("override_reason")
    if is_override:
        if actor.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
            raise CollectionError("Only ADMIN or ESG_MANAGER may record an entity-level override", 403)
        if not override_reason or not str(override_reason).strip():
            raise CollectionError("An override justification (override_reason) is required", 422)
    elif assignment.owner_user_id != actor.id and actor.role.name != "ADMIN":
        raise CollectionError("Only the assignment owner may edit this metric", 403)
    period = db.get(ReportingPeriod, assignment.period_id)
    if period is None:
        raise CollectionError("Reporting period not found", 500)
    if period.locked:
        raise CollectionError("Reporting period is locked; values cannot be modified")

    last = latest_value(db, assignment.id)
    if expected_last_version is not None and last is not None and last.version != expected_last_version:
        raise CollectionError(
            f"Concurrent edit detected: value is at version {last.version}, "
            f"you were editing version {expected_last_version}"
        )

    metric = _metric_for_assignment(db, assignment)

    # unit normalization (spec §10): every numeric value stores its canonical form
    normalized_value = normalized_unit = None
    if payload.get("raw_value") is not None:
        try:
            val = Decimal(str(payload["raw_value"]))
        except InvalidOperation:
            raise CollectionError("Value is not a valid number", 422)
        NON_NEGATIVE_FAMILIES = frozenset({
            "energy", "emissions", "water", "waste", "fuel_volume",
            "currency", "count", "workforce",
        })
        if metric.unit_family in NON_NEGATIVE_FAMILIES and val < 0:
            raise CollectionError(
                f"{metric.label} cannot be negative (received {val})", 422,
            )
        try:
            from app.normalization.units import UnitConversionError, normalize_value

            normalized_value, normalized_unit = normalize_value(
                payload["raw_value"], payload.get("raw_unit"),
                metric.unit_family, metric.canonical_unit,
            )
        except UnitConversionError as exc:
            raise CollectionError(str(exc), 422)

    if action == "SUBMIT":
        _structural_validate(metric, payload)
        # submit-stage gate: BLOCKING rules are evaluated against the incoming
        # payload (not the previously persisted version, which may not exist on
        # a first submission) and refuse the submission with 422. The full
        # deterministic sweep (cross-field, YoY, evidence, ...) runs at review.
        from types import SimpleNamespace

        from app.validation import engine as validation_engine

        candidate = SimpleNamespace(
            raw_value=Decimal(str(payload["raw_value"]))
            if payload.get("raw_value") is not None else None,
            raw_unit=payload.get("raw_unit"),
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            qualitative_value=payload.get("qualitative_value"),
            version=(last.version if last else 0) + 1,
        )
        blocking = [
            f
            for f in validation_engine.evaluate_assignment(db, assignment, "submit", value=candidate)
            if f.rule.severity == ValidationSeverity.BLOCKING
        ]
        if blocking:
            raise CollectionError(
                "Submission blocked by validation: " + "; ".join(f.message for f in blocking),
                422,
            )
        new_status = MetricValueStatus.SUBMITTED
        new_assignment_status = AssignmentStatus.SUBMITTED
    elif action == "SAVE_DRAFT":
        new_status = MetricValueStatus.IN_PROGRESS
        new_assignment_status = AssignmentStatus.IN_PROGRESS
    else:
        raise CollectionError("action must be SAVE_DRAFT or SUBMIT", 422)

    current_status = assignment.status
    if current_status == AssignmentStatus.LOCKED:
        raise CollectionError("Assignment is locked")
    if current_status not in (AssignmentStatus.NOT_STARTED, AssignmentStatus.IN_PROGRESS,
                              AssignmentStatus.NEEDS_CORRECTION, AssignmentStatus.REJECTED):
        raise CollectionError(
            f"Cannot edit a value in status {current_status.value}; "
            f"it is already {current_status.value}"
        )

    version = (last.version if last else 0) + 1
    value = MetricValue(
        assignment_id=assignment.id,
        version=version,
        raw_value=Decimal(str(payload["raw_value"])) if payload.get("raw_value") is not None else None,
        raw_unit=payload.get("raw_unit"),
        normalized_value=normalized_value,
        normalized_unit=normalized_unit,
        qualitative_value=payload.get("qualitative_value"),
        status=new_status,
        is_override=is_override,
        override_reason=override_reason if is_override else None,
        created_by=actor.id,
        submitted_by=actor.id if action == "SUBMIT" else None,
        submitted_at=datetime.now(UTC) if action == "SUBMIT" else None,
    )
    db.add(value)
    db.flush()

    assignment.status = new_assignment_status
    db.flush()

    record(
        db,
        action=AuditAction.SUBMITTED if action == "SUBMIT" else AuditAction.UPDATED,
        object_type="metric_value",
        object_id=value.id,
        actor_id=actor.id,
        actor_label=actor.email,
        entity_id=assignment.entity_id,
        metric_code=assignment.metric_code,
        old_value={"version": last.version, "raw_value": str(last.raw_value) if last else None}
        if last else None,
        new_value={"version": version, "raw_value": str(value.raw_value) if value.raw_value else None,
                   "raw_unit": value.raw_unit, "action": action, "is_override": is_override},
        reason="Entity-level override recorded" if is_override else None,
        request_id=request_id,
    )

    # dependent derived metrics recompute when an input changes; failures are
    # logged, never silent, and never block the owner's save
    if value.raw_value is not None:
        import logging

        from app.calculation import service as calc_service

        logger = logging.getLogger(__name__)
        try:
            calc_service.recompute_dependents(
                db, assignment.framework_version_id, assignment.entity_id,
                assignment.period_id, assignment.metric_code, actor=actor,
                request_id=request_id,
            )
        except Exception as exc:
            logger.warning(
                "dependent recompute failed for %s/%s: %s",
                assignment.entity_id, assignment.metric_code, exc,
            )
    return value


def review(
    db: Session,
    assignment: Assignment,
    *,
    action: str,
    actor: AppUser,
    comment: str | None = None,
    request_id: str | None = None,
) -> Assignment:
    if actor.role.name not in ("REVIEWER", "ESG_MANAGER", "ADMIN"):
        raise CollectionError("Only reviewers may perform review actions", 403)

    current = assignment.status
    if action == "START_REVIEW":
        if current != AssignmentStatus.SUBMITTED:
            raise CollectionError(f"Cannot start review from status {current.value}")
        # review-stage validation sweep: cross-field, cross-section, YoY,
        # duplicate, evidence completeness, logical consistency
        from app.validation import engine as validation_engine

        validation_engine.run_for_assignments(
            db, [assignment], "review", actor=actor, request_id=request_id
        )
        new_status = AssignmentStatus.UNDER_REVIEW
        audit_action = AuditAction.REVIEWED
    elif action == "APPROVE":
        if current != AssignmentStatus.UNDER_REVIEW:
            raise CollectionError(f"Cannot approve from status {current.value}")
        unresolved_blocking = db.scalar(
            select(ValidationException).where(
                ValidationException.assignment_id == assignment.id,
                ValidationException.severity == ValidationSeverity.BLOCKING,
                ValidationException.status != ValidationExceptionStatus.RESOLVED,
            )
        )
        if unresolved_blocking is not None:
            raise CollectionError(
                "Cannot approve: unresolved BLOCKING validation exceptions exist for this assignment"
            )
        unexplained_yoy = db.scalar(
            select(ValidationException).where(
                ValidationException.assignment_id == assignment.id,
                ValidationException.rule_code.like("%YOY%"),
                ValidationException.status == ValidationExceptionStatus.OPEN,
            )
        )
        if unexplained_yoy is not None and not comment and not unexplained_yoy.explanation:
            raise CollectionError(
                f"Cannot approve: significant year-on-year anomaly ({unexplained_yoy.rule_code}) requires an explanation",
                422,
            )
        new_status = AssignmentStatus.APPROVED
        audit_action = AuditAction.APPROVED
    elif action in ("NEEDS_CORRECTION", "REJECT"):
        if current != AssignmentStatus.UNDER_REVIEW:
            raise CollectionError(f"Cannot {action.lower()} from status {current.value}")
        if not comment or not comment.strip():
            raise CollectionError("A review comment is required", 422)
        new_status = (
            AssignmentStatus.NEEDS_CORRECTION
            if action == "NEEDS_CORRECTION"
            else AssignmentStatus.REJECTED
        )
        audit_action = AuditAction.REJECTED
    else:
        raise CollectionError("action must be START_REVIEW, APPROVE, NEEDS_CORRECTION or REJECT", 422)

    assignment.status = new_status
    value = latest_value(db, assignment.id)
    if value is not None:
        value.status = VALUE_STATUS_FOR_ASSIGNMENT[new_status]
    db.flush()

    if new_status == AssignmentStatus.APPROVED:
        # Automatically recompute every affected ancestor and dependent metric
        from app.consolidation.service import recompute_ancestors_on_approval

        try:
            recompute_ancestors_on_approval(
                db, assignment.entity_id, assignment.metric_code,
                assignment.period_id, actor=actor, request_id=request_id,
            )
        except Exception as exc:
            raise CollectionError(f"Approval failed during ancestor consolidation recomputation: {exc}", 500)
    record(
        db, action=audit_action, object_type="assignment", object_id=assignment.id,
        actor_id=actor.id, actor_label=actor.email,
        entity_id=assignment.entity_id, metric_code=assignment.metric_code,
        old_value={"status": current.value}, new_value={"status": new_status.value},
        reason=comment, request_id=request_id,
    )

    from app.notifications.router import notify_review

    if new_status == AssignmentStatus.APPROVED:
        notify_review(db, assignment, NotificationType.APPROVED,
                      f"{assignment.metric_code} was approved by {actor.email}")
    elif new_status in (AssignmentStatus.NEEDS_CORRECTION, AssignmentStatus.REJECTED):
        notify_review(db, assignment, NotificationType.RETURNED_FOR_CORRECTION,
                      f"{assignment.metric_code} returned by {actor.email}: {comment or ''}")
    return assignment
