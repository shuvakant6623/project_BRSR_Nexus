"""Reporting period API (spec §8). Locking arrives with the reporting engine."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models import AppUser, FrameworkVersion, ReportingPeriod

router = APIRouter(prefix="/api/v1/reporting-periods", tags=["reporting-periods"])


class PeriodOut(BaseModel):
    id: uuid.UUID
    label: str
    start_date: object
    end_date: object
    framework_version_id: uuid.UUID
    framework_version_code: str | None
    locked: bool


@router.get("", response_model=list[PeriodOut])
def list_periods(
    _user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PeriodOut]:
    periods = list(db.scalars(select(ReportingPeriod).order_by(ReportingPeriod.start_date)).all())
    out = []
    for p in periods:
        fv = db.get(FrameworkVersion, p.framework_version_id)
        out.append(
            PeriodOut(
                id=p.id, label=p.label, start_date=p.start_date, end_date=p.end_date,
                framework_version_id=p.framework_version_id,
                framework_version_code=fv.version_code if fv else None,
                locked=p.locked,
            )
        )
    return out
