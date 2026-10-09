"""Reporting API (spec §8, §18): period catalogue, locking, report generation."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import bearer_scheme, get_current_user, require_roles
from app.db.session import get_db
from app.logging import request_id_var
from app.models import (
    AppUser,
    FrameworkVersion,
    GeneratedReport,
    ReportingPeriod,
    ReportSnapshot,
)
from app.models.enums import AuditAction, JobStatus, UserRole
from app.reporting import service

router = APIRouter(tags=["reporting"])


class PeriodOut(BaseModel):
    id: uuid.UUID
    label: str
    start_date: object
    end_date: object
    framework_version_id: uuid.UUID
    framework_version_code: str | None
    locked: bool


class ReportOut(BaseModel):
    id: uuid.UUID
    period_id: uuid.UUID
    snapshot_id: uuid.UUID
    checksum: str | None
    status: JobStatus
    file_object_key: str | None
    error: str | None
    retry_count: int
    created_at: object
    completed_at: object | None


@router.get("/api/v1/reporting-periods", response_model=list[PeriodOut])
def list_periods(
    _user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PeriodOut]:
    periods = list(db.scalars(select(ReportingPeriod).order_by(ReportingPeriod.start_date)).all())
    out = []
    for p in periods:
        fv = db.get(FrameworkVersion, p.framework_version_id)
        out.append(PeriodOut(
            id=p.id, label=p.label, start_date=p.start_date, end_date=p.end_date,
            framework_version_id=p.framework_version_id,
            framework_version_code=fv.version_code if fv else None, locked=p.locked,
        ))
    return out


@router.post("/api/v1/reporting-periods/{period_id}/lock", response_model=PeriodOut)
def lock_period(
    period_id: uuid.UUID,
    request: Request,
    user: AppUser = Depends(require_roles(UserRole.ADMIN, UserRole.ESG_MANAGER)),
    db: Session = Depends(get_db),
) -> PeriodOut:
    try:
        period = service.lock_period(db, period_id, user, request_id=request_id_var.get())
        db.commit()
    except service.ReportingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.refresh(period)
    fv = db.get(FrameworkVersion, period.framework_version_id)
    return PeriodOut(
        id=period.id, label=period.label, start_date=period.start_date,
        end_date=period.end_date, framework_version_id=period.framework_version_id,
        framework_version_code=fv.version_code if fv else None, locked=period.locked,
    )


@router.post("/api/v1/reports/{period_id}/generate", response_model=ReportOut, status_code=202)
def generate_report(
    period_id: uuid.UUID,
    request: Request,
    user: AppUser = Depends(require_roles(UserRole.ADMIN, UserRole.ESG_MANAGER)),
    db: Session = Depends(get_db),
) -> ReportOut:
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reporting period not found")
    if not period.locked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Reports may only be generated from a LOCKED reporting period")
    try:
        snapshot = service.create_snapshot(db, period_id, user, request_id=request_id_var.get())
    except service.ReportingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    report = GeneratedReport(
        period_id=period_id, snapshot_id=snapshot.id, status=JobStatus.PENDING,
        created_by=user.id, request_id=request_id_var.get(),
    )
    db.add(report)
    db.flush()
    record(
        db, action=AuditAction.CREATED, object_type="generated_report", object_id=report.id,
        actor_id=user.id, actor_label=user.email,
        new_value={"period": period.label, "snapshot": str(snapshot.id)},
        request_id=request_id_var.get(),
    )
    db.commit()

    from app.workers.tasks import generate_report as task

    task.delay(str(report.id))
    db.refresh(report)
    return ReportOut(
        id=report.id, period_id=report.period_id, snapshot_id=report.snapshot_id,
        checksum=snapshot.checksum, status=report.status,
        file_object_key=report.file_object_key, error=report.error,
        retry_count=report.retry_count, created_at=report.created_at,
        completed_at=report.completed_at,
    )


@router.get("/api/v1/reports/{period_id}", response_model=list[ReportOut])
def list_reports(
    period_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReportOut]:
    reports = list(
        db.scalars(
            select(GeneratedReport)
            .where(GeneratedReport.period_id == period_id)
            .order_by(GeneratedReport.created_at.desc())
        ).all()
    )
    out = []
    for r in reports:
        snapshot = db.get(ReportSnapshot, r.snapshot_id)
        out.append(ReportOut(
            id=r.id, period_id=r.period_id, snapshot_id=r.snapshot_id,
            checksum=snapshot.checksum if snapshot else None, status=r.status,
            file_object_key=r.file_object_key, error=r.error, retry_count=r.retry_count,
            created_at=r.created_at, completed_at=r.completed_at,
        ))
    return out


@router.get("/api/v1/reports/{period_id}/preview")
def report_preview(
    period_id: uuid.UUID,
    token: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.auth.security import decode_token

    user = None
    if credentials is not None:
        try:
            payload = decode_token(credentials.credentials, expected_type="access")
            user = db.get(AppUser, uuid.UUID(payload["sub"]))
        except Exception:
            pass
    if user is None and token:
        try:
            payload = decode_token(token, expected_type="access")
            user = db.get(AppUser, uuid.UUID(payload["sub"]))
        except Exception:
            pass
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    snapshot = db.scalar(select(ReportSnapshot).where(ReportSnapshot.period_id == period_id))
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No snapshot exists for this period; generate the report first")
    html = service.render_snapshot_html(db, snapshot.id)
    return HTMLResponse(content=html)


@router.get("/api/v1/reports/{period_id}/download")
def download_report(
    period_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    report = db.scalar(
        select(GeneratedReport)
        .where(GeneratedReport.period_id == period_id, GeneratedReport.status == JobStatus.SUCCESS)
        .order_by(GeneratedReport.created_at.desc())
        .limit(1)
    )
    if report is None or report.file_object_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No generated PDF available for this period yet")
    from app.infra import storage

    return {"url": storage.presigned_get(report.file_object_key), "expires_in_hours": 1}
