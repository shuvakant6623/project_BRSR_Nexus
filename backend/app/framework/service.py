"""Framework metadata validation and management services.

Used by both the seed and the API so metadata authored anywhere goes through
the same invariants (DB constraints remain the last line of defense).
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FormulaDefinition,
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


def create_framework_version(db: Session, data: dict) -> FrameworkVersion:
    existing = db.scalar(
        select(FrameworkVersion).where(FrameworkVersion.version_code == data["version_code"])
    )
    if existing:
        raise FrameworkMetadataError(f"Framework version code '{data['version_code']}' already exists")
    effective_from = data.get("effective_from")
    effective_to = data.get("effective_to")
    if effective_from and effective_to and effective_to < effective_from:
        raise FrameworkMetadataError("effective_to must be on or after effective_from")
    version = FrameworkVersion(**data)
    db.add(version)
    db.flush()
    return version


def activate_version(db: Session, version_id: uuid.UUID) -> FrameworkVersion:
    version = db.get(FrameworkVersion, version_id)
    if version is None:
        raise FrameworkMetadataError("Framework version not found")

    # Check for date overlaps with other active framework versions
    active_versions = list(
        db.scalars(
            select(FrameworkVersion).where(
                FrameworkVersion.id != version_id,
                FrameworkVersion.is_active.is_(True),
            )
        ).all()
    )
    v_start = version.effective_from
    v_end = version.effective_to
    for other in active_versions:
        o_start = other.effective_from
        o_end = other.effective_to
        # If dates are defined, check for overlap
        if v_start and o_start:
            no_overlap = (v_end and v_end < o_start) or (o_end and v_start > o_end)
            if not no_overlap:
                raise FrameworkMetadataError(
                    f"Conflict: Version dates [{v_start} to {v_end or 'open'}] overlap with "
                    f"already active version '{other.version_code}' [{o_start} to {o_end or 'open'}]"
                )

    version.is_active = True
    db.flush()
    return version


def audit_framework_coverage(db: Session, version_id: uuid.UUID) -> dict:
    version = db.get(FrameworkVersion, version_id)
    if version is None:
        raise FrameworkMetadataError("Framework version not found")

    metrics = list(
        db.scalars(
            select(MetricDefinition).where(MetricDefinition.framework_version_id == version_id)
        ).all()
    )

    sections_found = {m.section for m in metrics}
    principles_found = {m.principle for m in metrics if m.principle}
    all_principles = [f"P{i}" for i in range(1, 10)]
    missing_principles = [p for p in all_principles if p not in principles_found]
    core_metrics = [m for m in metrics if m.brsr_core]

    # Validate ratios
    codes = {m.metric_code for m in metrics}
    ratio_defects = []
    for m in metrics:
        if m.aggregation_semantics == AggregationSemantics.RATIO_RECALCULATION:
            if not m.ratio_numerator_code or m.ratio_numerator_code not in codes:
                ratio_defects.append(f"{m.metric_code}: numerator '{m.ratio_numerator_code}' missing")
            if not m.ratio_denominator_code or m.ratio_denominator_code not in codes:
                ratio_defects.append(f"{m.metric_code}: denominator '{m.ratio_denominator_code}' missing")

    has_all_sections = {"A", "B", "C"}.issubset(sections_found)
    has_all_principles = len(missing_principles) == 0
    has_core = len(core_metrics) >= 9

    is_compliant = has_all_sections and has_all_principles and has_core and len(ratio_defects) == 0

    return {
        "version_id": str(version_id),
        "version_code": version.version_code,
        "is_active": version.is_active,
        "total_metrics": len(metrics),
        "sections": sorted(list(sections_found)),
        "missing_sections": sorted(list({"A", "B", "C"} - sections_found)),
        "principles_covered": sorted(list(principles_found)),
        "missing_principles": missing_principles,
        "core_indicator_count": len(core_metrics),
        "core_metric_codes": [m.metric_code for m in core_metrics],
        "ratio_defects": ratio_defects,
        "is_coverage_complete": is_compliant,
    }

