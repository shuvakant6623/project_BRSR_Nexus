"""Organization hierarchy model (adjacency list, traversed via recursive CTE)."""
import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EntityType


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_dates_ordered",
        ),
        Index("ix_entity_parent_id", "parent_id"),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entity.id", ondelete="RESTRICT")
    )
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type", native_enum=True), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    reporting_boundary_notes: Mapped[str | None] = mapped_column(Text)

    parent: Mapped["Entity | None"] = relationship(
        remote_side="Entity.id", back_populates="children"
    )
    children: Mapped[list["Entity"]] = relationship(back_populates="parent")
