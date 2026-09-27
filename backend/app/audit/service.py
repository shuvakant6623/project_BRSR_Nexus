"""Audit service — shared dependency, must not import business modules.

record() adds an audit event to the caller's session so it commits in the
SAME transaction as the business write. If the audit insert fails, the whole
transaction rolls back (never silently swallowed).
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.models.enums import AuditAction


def record(
    session: Session,
    action: AuditAction,
    object_type: str,
    object_id: uuid.UUID | str | None = None,
    actor_id: uuid.UUID | None = None,
    actor_label: str = "system",
    entity_id: uuid.UUID | None = None,
    metric_code: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    evidence_reference: uuid.UUID | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        actor_label=actor_label or "system",
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id else None,
        entity_id=str(entity_id) if entity_id else None,
        metric_code=metric_code,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        evidence_reference=str(evidence_reference) if evidence_reference else None,
        request_id=request_id,
    )
    session.add(event)
    session.flush()
    return event
