"""Reporting-period read endpoints. Lock/snapshot generation arrive with the
reporting engine phase; this router only exposes the period catalogue that
frontend flows (validation run, dashboards) need to pick an active period."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models import AppUser, ReportingPeriod

router = APIRouter(prefix="/api/v1/reporting-periods", tags=["reporting-periods"])


class PeriodOut(BaseModel):
    id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    locked: bool
    framework_version_id: uuid.UUID


@router.get("", response_model=list[PeriodOut])
def list_periods(
    _user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PeriodOut]:
    periods = db.scalars(select(ReportingPeriod).order_by(ReportingPeriod.start_date)).all()
    return [
        PeriodOut(
            id=p.id,
            label=p.label,
            start_date=p.start_date,
            end_date=p.end_date,
            locked=p.locked,
            framework_version_id=p.framework_version_id,
        )
        for p in periods
    ]
