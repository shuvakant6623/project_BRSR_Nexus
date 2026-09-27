"""Immutable report snapshots and asynchronously generated report files."""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import JobStatus


class ReportSnapshot(UUIDPrimaryKeyMixin, Base):
    """Immutable point-in-time copy of every reported value for a locked
    period. Reports are generated ONLY from this snapshot."""

    __tablename__ = "report_snapshot"
    __table_args__ = (
        UniqueConstraint("period_id"),
        CheckConstraint("checksum IS NOT NULL", name="checksum_present"),
    )

    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reporting_period.id", ondelete="RESTRICT"), nullable=False
    )
    framework_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("framework_version.id", ondelete="RESTRICT"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GeneratedReport(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "generated_report"
    __table_args__ = (Index("ix_generated_report_period", "period_id"),)

    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reporting_period.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_snapshot.id", ondelete="RESTRICT"), nullable=False
    )
    file_format: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf")
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=True), nullable=False,
        default=JobStatus.PENDING,
    )
    file_object_key: Mapped[str | None] = mapped_column(String(500))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
