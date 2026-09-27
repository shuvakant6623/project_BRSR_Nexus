"""Notifications, AI suggestions and bulk-import jobs."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import AISuggestionStatus, JobStatus, NotificationType


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_recipient", "recipient_user_id", "read_at"),)

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", native_enum=True), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AISuggestion(UUIDPrimaryKeyMixin, Base):
    """Draft-only AI output. Accepting a suggestion creates an owner-authored
    IN_PROGRESS MetricValue; a suggestion can never be SUBMITTED/APPROVED/LOCKED."""

    __tablename__ = "ai_suggestion"
    __table_args__ = (Index("ix_ai_suggestion_evidence", "evidence_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str | None] = mapped_column(String(100))
    candidate_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    candidate_unit: Mapped[str | None] = mapped_column(String(50))
    candidate_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="local_demo")
    status: Mapped[AISuggestionStatus] = mapped_column(
        Enum(AISuggestionStatus, name="ai_suggestion_status", native_enum=True),
        nullable=False,
        default=AISuggestionStatus.PENDING,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BulkImportJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bulk_import_job"
    __table_args__ = (Index("ix_bulk_import_job_uploader", "uploaded_by"),)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reporting_period.id", ondelete="RESTRICT"), nullable=False
    )
    file_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=True), nullable=False,
        default=JobStatus.PENDING,
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_report_object_key: Mapped[str | None] = mapped_column(String(500))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
