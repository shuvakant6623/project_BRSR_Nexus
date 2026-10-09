"""Bulk CSV import (spec §21): personalized template, async Celery processing
with the SAME validation engine as manual entry, rows become drafts — never
auto-submitted; invalid rows go to an error report in object storage."""
import csv
import io
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.config import get_settings
from app.infra import storage
from app.models import (
    AppUser,
    Assignment,
    Entity,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
)
from app.models.enums import AssignmentStatus, AuditAction, MetricValueStatus


class ImportError_(Exception):
    pass


TEMPLATE_HEADER = ["metric_code", "entity_name", "value", "unit"]


def build_template(db: Session, user: AppUser) -> tuple[str, str]:
    """CSV template prefilled with the user's assigned metric/entity pairs."""
    rows = [TEMPLATE_HEADER]
    assignments = list(
        db.scalars(
            select(Assignment).where(
                Assignment.owner_user_id == user.id,
                Assignment.status.in_([AssignmentStatus.NOT_STARTED, AssignmentStatus.IN_PROGRESS]),
            )
        ).all()
    )
    entities = {e.id: e for e in db.scalars(select(Entity)).all()}
    metrics = {
        m.metric_code: m
        for m in db.scalars(select(MetricDefinition)).all()
    }
    for a in assignments[:200]:
        metric = metrics.get(a.metric_code)
        unit = (metric.allowed_units or [metric.canonical_unit])[0] if metric else ""
        rows.append([a.metric_code, entities[a.entity_id].name if a.entity_id in entities else "", "", unit])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue(), f"brsr-import-template-{datetime.now(UTC).date()}.csv"


def process_import(
    db: Session, job_id: uuid.UUID, actor_id: uuid.UUID
) -> dict:
    """Celery entry point: parse the uploaded CSV, create draft values for
    valid rows, collect per-row errors into a report file."""
    from app.models import BulkImportJob

    job = db.get(BulkImportJob, job_id)
    if job is None:
        raise ImportError_("import job not found")
    settings = get_settings()
    job.status = "RUNNING"
    job.started_at = datetime.now(UTC)
    db.commit()

    client = storage.get_client()
    response = client.get_object(settings.s3_bucket, job.file_object_key)
    try:
        content = response.read().decode("utf-8-sig")
    finally:
        response.close()
        response.release_conn()

    reader = csv.DictReader(io.StringIO(content))
    errors: list[dict] = []
    valid = 0
    total = 0

    user = db.get(AppUser, job.uploaded_by)
    entities = {e.name: e for e in db.scalars(select(Entity)).all()}

    for line_no, row in enumerate(reader, start=2):
        total += 1
        code = (row.get("metric_code") or "").strip()
        entity_name = (row.get("entity_name") or "").strip()
        raw = (row.get("value") or "").strip()
        unit = (row.get("unit") or "").strip() or None

        def err(msg, *, line=line_no, code_=code, entity=entity_name):
            # defaults bind the current row's loop variables (B023)
            errors.append({"line": line, "metric_code": code_, "entity": entity, "error": msg})

        entity = entities.get(entity_name)
        if entity is None:
            err(f"unknown entity {entity_name!r}")
            continue
        assignment = db.scalar(
            select(Assignment).where(
                Assignment.metric_code == code,
                Assignment.entity_id == entity.id,
                Assignment.period_id == job.period_id,
                Assignment.owner_user_id == job.uploaded_by,
            )
        )
        if assignment is None:
            err("no matching assignment owned by you for metric/entity/period")
            continue
        period = db.get(ReportingPeriod, job.period_id)
        if period is None or period.locked:
            err("reporting period is locked or missing")
            continue
        metric = db.scalar(
            select(MetricDefinition).where(
                MetricDefinition.framework_version_id == assignment.framework_version_id,
                MetricDefinition.metric_code == code,
            )
        )
        if metric is None:
            err("metric not in period framework")
            continue
        try:
            from decimal import Decimal

            value = Decimal(raw)
        except Exception:
            err(f"value {raw!r} is not a number")
            continue

        # structural validation identical to manual entry
        from app.collection.service import CollectionError, _structural_validate

        payload = {"raw_value": float(value), "raw_unit": unit}
        try:
            _structural_validate(metric, payload)
        except CollectionError as exc:
            err(str(exc))
            continue
        from app.normalization.units import UnitConversionError, normalize_value

        try:
            normalized, normalized_unit = normalize_value(
                value, unit, metric.unit_family, metric.canonical_unit
            )
        except UnitConversionError as exc:
            err(str(exc))
            continue

        last = db.scalar(
            select(MetricValue)
            .where(MetricValue.assignment_id == assignment.id)
            .order_by(MetricValue.version.desc())
            .limit(1)
        )
        mv = MetricValue(
            assignment_id=assignment.id,
            version=(last.version if last else 0) + 1,
            raw_value=value,
            raw_unit=unit,
            normalized_value=normalized,
            normalized_unit=normalized_unit,
            status=MetricValueStatus.IN_PROGRESS,  # draft — never auto-submitted
            created_by=actor_id,
        )
        db.add(mv)
        if assignment.status == AssignmentStatus.NOT_STARTED:
            assignment.status = AssignmentStatus.IN_PROGRESS
        db.flush()
        record(
            db, action=AuditAction.UPDATED, object_type="metric_value", object_id=mv.id,
            actor_id=actor_id, actor_label=user.email if user else "import",
            entity_id=assignment.entity_id, metric_code=code,
            new_value={"version": mv.version, "raw_value": str(value), "source": "bulk_import"},
        )
        valid += 1

    job.total_rows = total
    job.valid_rows = valid
    job.invalid_rows = len(errors)
    error_key = None
    if errors:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["line", "metric_code", "entity", "error"])
        writer.writeheader()
        writer.writerows(errors)
        error_key = f"imports/{job_id}/errors.csv"
        client.put_object(
            settings.s3_bucket, error_key, io.BytesIO(buf.getvalue().encode()),
            length=len(buf.getvalue()), content_type="text/csv",
        )
        job.error_report_object_key = error_key
    job.status = "SUCCESS"
    job.completed_at = datetime.now(UTC)
    db.commit()
    return {
        "job_id": str(job_id), "total": total, "valid": valid,
        "invalid": len(errors), "error_report": error_key,
    }
