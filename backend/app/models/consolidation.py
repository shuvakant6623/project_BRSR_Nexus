"""Consolidation read-model traces (one current trace per entity/metric/period)."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ConsolidationTrace(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "consolidation_trace"
    __table_args__ = (
        UniqueConstraint("entity_id", "metric_code", "period_id"),
        Index("ix_consolidation_trace_period", "period_id"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reporting_period.id", ondelete="CASCADE"), nullable=False
    )
    value_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("metric_value.id", ondelete="SET NULL")
    )
    computed_value: Mapped[float | None] = mapped_column(Numeric(28, 8))
    unit: Mapped[str | None] = mapped_column(String(50))
    contributing_value_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    aggregation_semantics: Mapped[str | None] = mapped_column(String(30))
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_reason: Mapped[str | None] = mapped_column(String(255))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
