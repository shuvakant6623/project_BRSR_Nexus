"""BRSR framework metadata: versions, metrics, formulas, cross-version lineage."""
import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AggregationSemantics, MetricDataType

SECTION_VALUES = "section IN ('A', 'B', 'C')"


class FrameworkVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "framework_version"

    version_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    metrics: Mapped[list["MetricDefinition"]] = relationship(back_populates="framework_version")


class FormulaDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "formula_definition"
    __table_args__ = (UniqueConstraint("framework_version_id", "code"),)

    framework_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("framework_version.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    versions: Mapped[list["FormulaVersion"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )


class FormulaVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "formula_version"
    __table_args__ = (
        UniqueConstraint("formula_definition_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    formula_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formula_definition.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    input_metric_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    constants: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    definition: Mapped[FormulaDefinition] = relationship(back_populates="versions")


class MetricDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "metric_definition"
    __table_args__ = (
        UniqueConstraint("framework_version_id", "metric_code"),
        CheckConstraint(SECTION_VALUES, name="section_valid"),
        CheckConstraint(
            "section <> 'C' OR principle IS NOT NULL", name="section_c_requires_principle"
        ),
        CheckConstraint(
            "aggregation_semantics <> 'RATIO_RECALCULATION' OR "
            "(ratio_numerator_code IS NOT NULL AND ratio_denominator_code IS NOT NULL)",
            name="ratio_requires_numerator_denominator",
        ),
        CheckConstraint("display_order IS NULL OR display_order >= 0", name="display_order_valid"),
    )

    framework_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("framework_version.id", ondelete="RESTRICT"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    question_code: Mapped[str | None] = mapped_column(String(50))
    section: Mapped[str] = mapped_column(String(1), nullable=False)
    principle: Mapped[str | None] = mapped_column(String(2))
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[MetricDataType] = mapped_column(
        Enum(MetricDataType, name="metric_data_type", native_enum=True), nullable=False
    )
    unit_family: Mapped[str | None] = mapped_column(String(50))
    allowed_units: Mapped[list | None] = mapped_column(JSONB)
    canonical_unit: Mapped[str | None] = mapped_column(String(50))
    scope: Mapped[str | None] = mapped_column(String(100))
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    applicability_rule: Mapped[dict | None] = mapped_column(JSONB)
    aggregation_semantics: Mapped[AggregationSemantics] = mapped_column(
        Enum(AggregationSemantics, name="aggregation_semantics", native_enum=True), nullable=False
    )
    ratio_numerator_code: Mapped[str | None] = mapped_column(String(100))
    ratio_denominator_code: Mapped[str | None] = mapped_column(String(100))
    calculation_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("formula_definition.id", ondelete="SET NULL")
    )
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    brsr_core: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_reference: Mapped[str | None] = mapped_column(String(255))
    display_order: Mapped[int | None] = mapped_column(Integer)

    framework_version: Mapped[FrameworkVersion] = relationship(back_populates="metrics")
    calculation_rule: Mapped[FormulaDefinition | None] = relationship()


class MetricLineage(UUIDPrimaryKeyMixin, Base):
    """Maps metrics across framework versions so trends never compare
    differently-defined metrics silently."""

    __tablename__ = "metric_lineage"
    __table_args__ = (
        UniqueConstraint(
            "from_framework_version_id",
            "from_metric_code",
            "to_framework_version_id",
            "to_metric_code",
        ),
    )

    from_framework_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("framework_version.id", ondelete="CASCADE"), nullable=False
    )
    from_metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    to_framework_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("framework_version.id", ondelete="CASCADE"), nullable=False
    )
    to_metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    # DIRECT | RENAMED | REDEFINED | SPLIT
    mapping_type: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
