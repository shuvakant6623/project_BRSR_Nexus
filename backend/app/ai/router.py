"""AI suggestion API (spec §23): list, extract trigger, accept, reject."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.ai import service
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.logging import request_id_var
from app.models import AISuggestion, AppUser, Assignment, Evidence, MetricValue
from app.models.enums import AISuggestionStatus, AuditAction, UserRole

router = APIRouter(prefix="/api/v1/ai-suggestions", tags=["ai-suggestions"])


class SuggestionOut(BaseModel):
    id: uuid.UUID
    evidence_id: uuid.UUID
    metric_value_id: uuid.UUID | None
    assignment_id: uuid.UUID | None
    candidate_value: float | None
    candidate_unit: str | None
    confidence: float | None
    provider: str
    status: AISuggestionStatus


def _out(db: Session, s: AISuggestion) -> SuggestionOut:
    evidence = db.get(Evidence, s.evidence_id)
    mv = db.get(MetricValue, evidence.metric_value_id) if evidence else None
    assignment = db.get(Assignment, mv.assignment_id) if mv else None
    return SuggestionOut(
        id=s.id, evidence_id=s.evidence_id,
        metric_value_id=mv.id if mv else None,
        assignment_id=assignment.id if assignment else None,
        candidate_value=float(s.candidate_value) if s.candidate_value is not None else None,
        candidate_unit=s.candidate_unit,
        confidence=float(s.confidence) if s.confidence is not None else None,
        provider=s.provider, status=s.status,
    )


@router.post("/extract/{evidence_id}", status_code=202)
def extract(
    evidence_id: uuid.UUID,
    request: Request,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role != UserRole.DATA_OWNER and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only data owners may trigger extraction")
    evidence = db.get(Evidence, evidence_id)
    if evidence is None or evidence.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    result = service.extract_for_evidence(db, evidence_id)
    record(
        db, action=AuditAction.CREATED, object_type="ai_suggestion",
        actor_id=user.id, actor_label=user.email,
        new_value={"evidence": str(evidence_id), "provider": result["provider"],
                   "suggestions": len(result["suggestions"])},
        request_id=request_id_var.get(),
    )
    db.commit()
    return {**result, "note": "demo extraction" if result["provider"] == "local_demo"
            else "extraction complete — suggestions are UNVERIFIED drafts"}


@router.get("", response_model=list[SuggestionOut])
def my_suggestions(
    pending_only: bool = Query(default=False),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SuggestionOut]:
    stmt = select(AISuggestion).order_by(AISuggestion.created_at.desc()).limit(50)
    if pending_only:
        stmt = stmt.where(AISuggestion.status == AISuggestionStatus.PENDING)
    rows = db.scalars(stmt).all()
    return [_out(db, s) for s in rows]


class AcceptBody(BaseModel):
    value: float | None = None
    unit: str | None = None


@router.post("/{suggestion_id}/accept")
def accept(
    suggestion_id: uuid.UUID,
    body: AcceptBody,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role != UserRole.DATA_OWNER and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the data owner may accept suggestions")
    from decimal import Decimal

    try:
        mv = service.accept_suggestion(
            db, suggestion_id, user,
            override_value=Decimal(str(body.value)) if body.value is not None else None,
            override_unit=body.unit,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"status": "ACCEPTED", "draft_value_id": str(mv.id) if mv else None,
            "note": "An owner-authored IN_PROGRESS draft was created — review and submit it manually"}


@router.post("/{suggestion_id}/reject")
def reject(
    suggestion_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role != UserRole.DATA_OWNER and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the data owner may reject suggestions")
    try:
        service.reject_suggestion(db, suggestion_id, user)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"status": "REJECTED"}
