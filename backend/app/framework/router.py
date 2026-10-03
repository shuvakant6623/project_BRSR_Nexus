"""Framework API: versions, metric metadata, formulas, validation rules.

Reads are available to any authenticated user (the dynamic form renderer and
role screens consume this). Writes are ADMIN-only and validated by the same
metadata service as the seed.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import get_current_user, require_roles
from app.config import get_settings
from app.db.session import get_db
from app.framework.service import FrameworkMetadataError, create_metric
from app.models import (
    AppUser,
    FormulaDefinition,
    FormulaVersion,
    FrameworkVersion,
    MetricDefinition,
    ValidationRule,
)
from app.models.enums import AuditAction, MetricDataType, UserRole

router = APIRouter(prefix="/api/v1/framework", tags=["framework"])
require_admin = require_roles(UserRole.ADMIN)


class FrameworkVersionOut(BaseModel):
    id: uuid.UUID
    version_code: str
    name: str
    description: str | None
    effective_from: object | None
    effective_to: object | None
    is_active: bool
    metric_count: int


class MetricOut(BaseModel):
    metric_code: str
    question_code: str | None
    section: str
    principle: str | None
    label: str
    description: str | None
    data_type: MetricDataType
    unit_family: str | None
    allowed_units: list | None
    canonical_unit: str | None
    scope: str | None
    required: bool
    applicability_rule: dict | None
    aggregation_semantics: str
    ratio_numerator_code: str | None
    ratio_denominator_code: str | None
    evidence_required: bool
    brsr_core: bool
    source_reference: str | None
    display_order: int | None


class MetricCreate(BaseModel):
    metric_code: str
    section: str
    principle: str | None = None
    label: str
    description: str | None = None
    data_type: MetricDataType
    unit_family: str | None = None
    allowed_units: list | None = None
    canonical_unit: str | None = None
    scope: str | None = None
    required: bool = True
    applicability_rule: dict | None = None
    aggregation_semantics: str
    ratio_numerator_code: str | None = None
    ratio_denominator_code: str | None = None
    evidence_required: bool = False
    brsr_core: bool = False
    source_reference: str | None = None
    display_order: int | None = None


class FormulaOut(BaseModel):
    code: str
    name: str
    description: str | None
    versions: list[dict]


class RuleOut(BaseModel):
    rule_code: str
    rule_class: str
    target_metric_code: str | None
    severity: str
    config: dict
    applies_on: str
    version: int
    message_template: str | None


@router.get("/versions", response_model=list[FrameworkVersionOut])
def list_versions(
    _user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FrameworkVersionOut]:
    versions = list(db.scalars(select(FrameworkVersion).order_by(FrameworkVersion.effective_from)).all())
    out = []
    for v in versions:
        count = len(
            db.scalars(
                select(MetricDefinition.metric_code).where(
                    MetricDefinition.framework_version_id == v.id
                )
            ).all()
        )
        out.append(
            FrameworkVersionOut(
                id=v.id, version_code=v.version_code, name=v.name,
                description=v.description, effective_from=v.effective_from,
                effective_to=v.effective_to, is_active=v.is_active,
                metric_count=count,
            )
        )
    return out


@router.get("/versions/{version_id}/metrics", response_model=list[MetricOut])
def list_metrics(
    version_id: uuid.UUID,
    section: str | None = Query(default=None),
    principle: str | None = Query(default=None),
    brsr_core: bool | None = Query(default=None),
    _user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MetricOut]:
    version = db.get(FrameworkVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Framework version not found")
    stmt = (
        select(MetricDefinition)
        .where(MetricDefinition.framework_version_id == version_id)
        .order_by(MetricDefinition.section, MetricDefinition.display_order.nulls_last())
    )
    if section:
        stmt = stmt.where(MetricDefinition.section == section)
    if principle:
        stmt = stmt.where(MetricDefinition.principle == principle)
    if brsr_core is not None:
        stmt = stmt.where(MetricDefinition.brsr_core.is_(brsr_core))
    return [
        MetricOut(
            metric_code=m.metric_code, question_code=m.question_code, section=m.section,
            principle=m.principle, label=m.label, description=m.description,
            data_type=m.data_type, unit_family=m.unit_family, allowed_units=m.allowed_units,
            canonical_unit=m.canonical_unit, scope=m.scope, required=m.required,
            applicability_rule=m.applicability_rule,
            aggregation_semantics=m.aggregation_semantics.value,
            ratio_numerator_code=m.ratio_numerator_code,
            ratio_denominator_code=m.ratio_denominator_code,
            evidence_required=m.evidence_required, brsr_core=m.brsr_core,
            source_reference=m.source_reference, display_order=m.display_order,
        )
        for m in db.scalars(stmt).all()
    ]


@router.post("/versions/{version_id}/metrics", response_model=MetricOut, status_code=201)
def add_metric(
    version_id: uuid.UUID,
    body: MetricCreate,
    user: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MetricOut:
    version = db.get(FrameworkVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Framework version not found")
    data = body.model_dump()
    data["aggregation_semantics"] = body.aggregation_semantics
    try:
        metric = create_metric(db, version_id, data)
        record(
            db, action=AuditAction.CREATED, object_type="metric_definition",
            object_id=metric.id, actor_id=user.id, actor_label=user.email,
            metric_code=metric.metric_code,
            new_value={"metric_code": metric.metric_code, "section": metric.section,
                       "label": metric.label},
        )
        db.commit()
    except FrameworkMetadataError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.refresh(metric)
    return MetricOut(
        metric_code=metric.metric_code, question_code=metric.question_code,
        section=metric.section, principle=metric.principle, label=metric.label,
        description=metric.description, data_type=metric.data_type,
        unit_family=metric.unit_family, allowed_units=metric.allowed_units,
        canonical_unit=metric.canonical_unit, scope=metric.scope, required=metric.required,
        applicability_rule=metric.applicability_rule,
        aggregation_semantics=metric.aggregation_semantics.value,
        ratio_numerator_code=metric.ratio_numerator_code,
        ratio_denominator_code=metric.ratio_denominator_code,
        evidence_required=metric.evidence_required, brsr_core=metric.brsr_core,
        source_reference=metric.source_reference, display_order=metric.display_order,
    )


@router.get("/versions/{version_id}/formulas", response_model=list[FormulaOut])
def list_formulas(
    version_id: uuid.UUID,
    _user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FormulaOut]:
    definitions = list(
        db.scalars(
            select(FormulaDefinition).where(
                FormulaDefinition.framework_version_id == version_id
            )
        ).all()
    )
    out = []
    for d in definitions:
        versions = list(
            db.scalars(
                select(FormulaVersion).where(FormulaVersion.formula_definition_id == d.id)
            ).all()
        )
        out.append(
            FormulaOut(
                code=d.code, name=d.name, description=d.description,
                versions=[
                    {"version": fv.version, "expression": fv.expression,
                     "input_metric_codes": fv.input_metric_codes, "constants": fv.constants}
                    for fv in versions
                ],
            )
        )
    return out


@router.get("/versions/{version_id}/rules", response_model=list[RuleOut])
def list_rules(
    version_id: uuid.UUID,
    _user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RuleOut]:
    rules = list(
        db.scalars(
            select(ValidationRule).where(ValidationRule.framework_version_id == version_id)
        ).all()
    )
    return [
        RuleOut(
            rule_code=r.rule_code, rule_class=r.rule_class.value,
            target_metric_code=r.target_metric_code, severity=r.severity.value,
            config=r.config, applies_on=r.applies_on, version=r.version,
            message_template=r.message_template,
        )
        for r in rules
    ]
