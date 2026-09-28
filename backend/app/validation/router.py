"""Validation API: run rules, list exceptions, explain, resolve."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import get_current_user, get_scoped_entity_ids
from app.collection import service as collection_service
from app.db.session import get_db
from app.logging import request_id_var
from app.models import (
    AppUser,
    Assignment,
    Entity,
    ReportingPeriod,
    ValidationException,
)
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    ValidationExceptionStatus,
    UserRole,
    ValidationSeverity,
)
from app.validation import engine

router = APIRouter(prefix="/api/v1/validation", tags=["validation"])


class ValidationRun(BaseModel):
    period_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None


class ExceptionOut(BaseModel):
    id: uuid.UUID
    rule_code: str
    rule_version: int
    severity: ValidationSeverity
    message: str
    entity_id: uuid.UUID
    metric_code: str | None
    period_id: uuid.UUID | None
    assignment_id: uuid.UUID | None
    observed_value: float | None
    status: ValidationExceptionStatus
    explanation: str | None
    explained_by: uuid.UUID | None
    resolved_at: object | None
    created_at: object


class ExplainBody(BaseModel):
    explanation: str = Field(min_length=5)


def _out(e: ValidationException) -> ExceptionOut:
    return ExceptionOut(
        id=e.id, rule_code=e.rule_code, rule_version=e.rule_version, severity=e.severity,
        message=e.message, entity_id=e.entity_id, metric_code=e.metric_code,
        period_id=e.period_id, assignment_id=e.assignment_id,
        observed_value=float(e.observed_value) if e.observed_value is not None else None,
        status=e.status, explanation=e.explanation, explained_by=e.explained_by,
        resolved_at=e.resolved_at, created_at=e.created_at,
    )


def _scoped_exception(db: Session, exception_id: uuid.UUID, user: AppUser,
                      scoped_ids: set[uuid.UUID]) -> ValidationException:
    exception = db.get(ValidationException, exception_id)
    if exception is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER) and exception.entity_id not in scoped_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Exception outside your authorized scope")
    return exception


@router.post("/run")
def run_validation(
    body: ValidationRun,
    request: Request,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER, UserRole.REVIEWER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only reviewers, ESG managers and admins may run validation")
    period = db.get(ReportingPeriod, body.period_id)
    if period is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reporting period not found")

    stmt = select(Assignment).where(Assignment.period_id == body.period_id)
    if body.assignment_id:
        stmt = stmt.where(Assignment.id == body.assignment_id)
    if body.entity_id:
        stmt = stmt.where(Assignment.entity_id == body.entity_id)
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        stmt = stmt.where(Assignment.entity_id.in_(scoped_ids))
    assignments = list(db.scalars(stmt).all())

    # stage selection: submitted/under-review assignments get the full review-stage
    # sweep; everything else gets submit-stage checks (required/range/unit/type)
    totals = {"assignments": 0, "raised": 0, "auto_resolved": 0, "blocking": 0}
    for assignment in assignments:
        stage = (
            "review"
            if assignment.status
            in (AssignmentStatus.SUBMITTED, AssignmentStatus.UNDER_REVIEW, AssignmentStatus.APPROVED)
            else "submit"
        )
        result = engine.run_for_assignments(
            db, [assignment], stage, actor=user, request_id=request_id_var.get()
        )
        for key in totals:
            totals[key] += result[key]
    db.commit()
    return {"status": "completed", **totals}


@router.get("/exceptions", response_model=list[ExceptionOut])
def list_exceptions(
    period_id: uuid.UUID | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    exception_status: ValidationExceptionStatus | None = Query(default=None, alias="status"),
    severity: ValidationSeverity | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> list[ExceptionOut]:
    stmt = select(ValidationException).order_by(ValidationException.created_at.desc())
    if user.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        stmt = stmt.where(ValidationException.entity_id.in_(scoped_ids))
    if period_id:
        stmt = stmt.where(ValidationException.period_id == period_id)
    if entity_id:
        stmt = stmt.where(ValidationException.entity_id == entity_id)
    if exception_status:
        stmt = stmt.where(ValidationException.status == exception_status)
    if severity:
        stmt = stmt.where(ValidationException.severity == severity)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return [_out(e) for e in rows]


@router.post("/exceptions/{exception_id}/explain", response_model=ExceptionOut)
def explain_exception(
    exception_id: uuid.UUID,
    body: ExplainBody,
    request: Request,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> ExceptionOut:
    exception = _scoped_exception(db, exception_id, user, scoped_ids)
    if exception.status == ValidationExceptionStatus.RESOLVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Exception already resolved")
    # owners may explain only their own assignments; management/assessor cannot
    if user.role in (UserRole.REVIEWER, UserRole.ESG_MANAGER, UserRole.ADMIN):
        pass
    elif user.role == UserRole.DATA_OWNER:
        assignment = db.get(Assignment, exception.assignment_id) if exception.assignment_id else None
        if assignment is None or assignment.owner_user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="You may only explain exceptions on your own assignments")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your role cannot explain validation exceptions")
    exception.explanation = body.explanation
    exception.explained_by = user.id
    exception.explained_at = exception.explained_at or datetime.now(UTC)
    exception.status = ValidationExceptionStatus.EXPLAINED
    db.flush()
    record(
        db, action=AuditAction.EXPLANATION_ADDED, object_type="validation_exception",
        object_id=exception.id, actor_id=user.id, actor_label=user.email,
        entity_id=exception.entity_id, metric_code=exception.metric_code,
        new_value={"explanation": body.explanation}, request_id=request_id_var.get(),
    )
    db.commit()
    db.refresh(exception)
    return _out(exception)


@router.post("/exceptions/{exception_id}/resolve", response_model=ExceptionOut)
def resolve_exception(
    exception_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    scoped_ids: set[uuid.UUID] = Depends(get_scoped_entity_ids),
    db: Session = Depends(get_db),
) -> ExceptionOut:
    exception = _scoped_exception(db, exception_id, user, scoped_ids)
    if user.role not in (UserRole.REVIEWER, UserRole.ESG_MANAGER, UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only reviewers, ESG managers and admins may resolve exceptions")
    exception.status = ValidationExceptionStatus.RESOLVED
    exception.resolved_by = user.id
    exception.resolved_at = datetime.now(UTC)
    db.flush()
    record(
        db, action=AuditAction.UPDATED, object_type="validation_exception",
        object_id=exception.id, actor_id=user.id, actor_label=user.email,
        entity_id=exception.entity_id, metric_code=exception.metric_code,
        new_value={"status": "RESOLVED"}, reason="manually resolved",
        request_id=request_id_var.get(),
    )
    db.commit()
    db.refresh(exception)
    return _out(exception)
