"""Append-only audit trail. No UPDATE/DELETE paths exist by design; the
migration additionally installs a database trigger rejecting mutations."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import AuditAction


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_entity", "entity_id"),
        Index("ix_audit_event_object", "object_type", "object_id"),
        Index("ix_audit_event_created", "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    actor_label: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", native_enum=True), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(String(64))
    metric_code: Mapped[str | None] = mapped_column(String(100))
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_reference: Mapped[uuid.UUID | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
