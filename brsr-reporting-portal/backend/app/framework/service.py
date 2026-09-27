"""Framework metadata validation and management services.

Used by both the seed and the API so metadata authored anywhere goes through
the same invariants (DB constraints remain the last line of defense).
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FormulaDefinition,
    FrameworkVersion,
    MetricDefinition,
)
from app.models.enums import AggregationSemantics, MetricDataType

VALID_SECTIONS = ("A", "B", "C")


class FrameworkMetadataError(Exception):
    pass


def validate_metric_definition(db: Session, framework_version_id: uuid.UUID, data: dict) -> None:
    section = data.get("section")
    if section not in VALID_SECTIONS:
        raise FrameworkMetadataError(f"Invalid section {section!r}; must be A, B or C")

    if section == "C" and not data.get("principle"):
        raise FrameworkMetadataError("Section C metric requires a principle (P1..P9)")
    if data.get("principle") and section != "C":
        raise FrameworkMetadataError("Only Section C metrics carry a principle")

    agg = data.get("aggregation_semantics")
    num = data.get("ratio_numerator_code")
    den = data.get("ratio_denominator_code")
    if agg == AggregationSemantics.RATIO_RECALCULATION and (not num or not den):
        raise FrameworkMetadataError(
            "RATIO_RECALCULATION metric requires ratio_numerator_code and ratio_denominator_code"
        )
    if (num or den) and agg != AggregationSemantics.RATIO_RECALCULATION:
        raise FrameworkMetadataError(
            "ratio_numerator_code/denominator_code are only valid for RATIO_RECALCULATION metrics"
        )
    if num and num == data.get("metric_code"):
        raise FrameworkMetadataError("A ratio metric cannot be its own numerator")
    if den and den == data.get("metric_code"):
        raise FrameworkMetadataError("A ratio metric cannot be its own denominator")

    # referenced codes must exist in the same framework version
    codes_in_version = set(
        db.scalars(
            select(MetricDefinition.metric_code).where(
                MetricDefinition.framework_version_id == framework_version_id
            )
        ).all()
    )
    for ref in (num, den):
        if ref and ref not in codes_in_version:
            raise FrameworkMetadataError(
                f"Ratio reference {ref!r} does not exist in this framework version"
            )

    if data.get("calculation_rule_id") is not None:
        formula = db.get(FormulaDefinition, data["calculation_rule_id"])
        if formula is None or formula.framework_version_id != framework_version_id:
            raise FrameworkMetadataError("calculation_rule_id references a formula from another framework version")

    canonical = data.get("canonical_unit")
    allowed = data.get("allowed_units")
    if data.get("data_type") == MetricDataType.NUMERIC:
        if not canonical:
            raise FrameworkMetadataError("Numeric metric requires a canonical_unit")
        if allowed and canonical not in allowed:
            raise FrameworkMetadataError("canonical_unit must be included in allowed_units")


def create_metric(db: Session, framework_version_id: uuid.UUID, data: dict) -> MetricDefinition:
    duplicate = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.framework_version_id == framework_version_id,
            MetricDefinition.metric_code == data["metric_code"],
        )
    )
    if duplicate:
        raise FrameworkMetadataError(
            f"metric_code {data['metric_code']!r} already exists in this framework version"
        )
    validate_metric_definition(db, framework_version_id, data)
    metric = MetricDefinition(framework_version_id=framework_version_id, **data)
    db.add(metric)
    db.flush()
    return metric
