"""Reporting engine (spec §18): period locking, immutable snapshots, async
HTML/PDF generation from the snapshot — never from live mutable data."""
import hashlib
import json
import uuid
from datetime import UTC, datetime

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.config import get_settings
from app.infra import storage
from app.models import (
    AppUser,
    Assignment,
    ConsolidationTrace,
    Entity,
    Evidence,
    GeneratedReport,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
    ReportSnapshot,
    UserEntityScope,
    ValidationException,
)
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    JobStatus,
    MetricValueStatus,
    UserRole,
    ValidationExceptionStatus,
    ValidationSeverity,
)


class ReportingError(Exception):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def lock_period(db: Session, period_id: uuid.UUID, actor: AppUser,
                request_id: str | None = None) -> ReportingPeriod:
    if actor.role not in (UserRole.ADMIN, UserRole.ESG_MANAGER):
        raise ReportingError("Only ADMIN or ESG_MANAGER may lock a reporting period", 403)
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise ReportingError("Reporting period not found", 404)
    if period.locked:
        raise ReportingError("Period is already locked")
    if period.end_date > datetime.now(UTC).date():
        raise ReportingError("Cannot lock a period that has not ended yet")

    assignments = list(db.scalars(select(Assignment).where(Assignment.period_id == period_id)).all())
    unapproved = [
        a for a in assignments
        if a.status not in (AssignmentStatus.APPROVED, AssignmentStatus.LOCKED)
    ]
    if unapproved:
        raise ReportingError(
            f"Cannot lock: {len(unapproved)} in-scope assignment(s) are not APPROVED "
            f"(first: {unapproved[0].metric_code})"
        )
    blocking = db.scalar(
        select(ValidationException.id).where(
            ValidationException.period_id == period_id,
            ValidationException.severity == ValidationSeverity.BLOCKING,
            ValidationException.status != ValidationExceptionStatus.RESOLVED,
        )
    )
    if blocking is not None:
        raise ReportingError("Cannot lock: unresolved BLOCKING validation exceptions exist")

    period.locked = True
    period.locked_at = datetime.now(UTC)
    period.locked_by = actor.id
    for a in assignments:
        a.status = AssignmentStatus.LOCKED
        latest = db.scalar(
            select(MetricValue)
            .where(MetricValue.assignment_id == a.id)
            .order_by(MetricValue.version.desc())
            .limit(1)
        )
        if latest is not None:
            latest.status = MetricValueStatus.LOCKED
    db.flush()
    record(
        db, action=AuditAction.LOCKED, object_type="reporting_period", object_id=period.id,
        actor_id=actor.id, actor_label=actor.email,
        new_value={"label": period.label}, reason="period locked for reporting",
        request_id=request_id,
    )
    return period


def create_snapshot(db: Session, period_id: uuid.UUID, actor: AppUser,
                    request_id: str | None = None) -> ReportSnapshot:
    """Immutable point-in-time copy of every approved value for the period."""
    period = db.get(ReportingPeriod, period_id)
    if period is None:
        raise ReportingError("Reporting period not found", 404)
    existing = db.scalar(select(ReportSnapshot).where(ReportSnapshot.period_id == period_id))
    if existing is not None:
        raise ReportingError("A snapshot already exists for this period (immutable)")

    traces = list(
        db.scalars(
            select(ConsolidationTrace).where(ConsolidationTrace.period_id == period_id)
        ).all()
    )
    incomplete = [t for t in traces if not t.is_complete or t.is_stale]
    if incomplete:
        raise ReportingError(
            f"Cannot create snapshot: {len(incomplete)} consolidation trace(s) are incomplete or stale "
            f"(first: {incomplete[0].metric_code})"
        )

    assignments = list(db.scalars(select(Assignment).where(Assignment.period_id == period_id)).all())
    payload: dict = {
        "period": period.label,
        "framework_version_id": str(period.framework_version_id),
        "values": [],
        "consolidated": [],
    }
    for a in assignments:
        value = db.scalar(
            select(MetricValue)
            .where(MetricValue.assignment_id == a.id)
            .order_by(MetricValue.version.desc())
            .limit(1)
        )
        if value is None:
            continue
        evidence = list(
            db.scalars(
                select(Evidence).where(
                    Evidence.metric_value_id == value.id, Evidence.is_deleted.is_(False)
                )
            ).all()
        )
        uploader = db.get(AppUser, value.created_by)
        payload["values"].append({
            "entity_id": str(a.entity_id),
            "metric_code": a.metric_code,
            "raw_value": str(value.raw_value) if value.raw_value is not None else None,
            "raw_unit": value.raw_unit,
            "normalized_value": str(value.normalized_value) if value.normalized_value is not None else None,
            "normalized_unit": value.normalized_unit,
            "is_calculated": value.is_calculated,
            "formula_version": value.formula_version,
            "is_override": getattr(value, "is_override", False),
            "override_reason": getattr(value, "override_reason", None),
            "status": value.status.value,
            "submitted_by": uploader.email if uploader else None,
            "submitted_at": value.submitted_at.isoformat() if value.submitted_at else None,
            "evidence": [
                {"filename": ev.original_filename, "sha256": ev.sha256_hash} for ev in evidence
            ],
        })

    for t in traces:
        ent = db.get(Entity, t.entity_id)
        met = db.scalar(
            select(MetricDefinition).where(
                MetricDefinition.framework_version_id == period.framework_version_id,
                MetricDefinition.metric_code == t.metric_code,
            )
        )
        payload["consolidated"].append({
            "entity_id": str(t.entity_id),
            "entity_name": ent.name if ent else "?",
            "metric_code": t.metric_code,
            "metric_label": met.label if met else t.metric_code,
            "section": met.section if met else "?",
            "principle": met.principle if met else None,
            "computed_value": str(t.computed_value) if t.computed_value is not None else None,
            "unit": t.unit,
            "aggregation_semantics": t.aggregation_semantics,
            "is_complete": t.is_complete,
            "is_stale": t.is_stale,
            "contributing_value_count": len(t.contributing_value_ids or []),
        })

    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    snapshot = ReportSnapshot(
        period_id=period_id,
        framework_version_id=period.framework_version_id,
        payload=payload,
        checksum=checksum,
        created_by=actor.id,
    )
    db.add(snapshot)
    db.flush()
    record(
        db, action=AuditAction.CREATED, object_type="report_snapshot", object_id=snapshot.id,
        actor_id=actor.id, actor_label=actor.email,
        new_value={
            "period": period.label, "checksum": checksum,
            "values": len(payload["values"]), "consolidated": len(payload["consolidated"]),
        },
        request_id=request_id,
    )
    return snapshot


def render_snapshot_html(db: Session, snapshot_id: uuid.UUID) -> str:
    snapshot = db.get(ReportSnapshot, snapshot_id)
    if snapshot is None:
        raise ReportingError("Snapshot not found", 404)
    period = db.get(ReportingPeriod, snapshot.period_id)
    by_section: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    for v in snapshot.payload["values"]:
        metric = db.scalar(
            select(MetricDefinition).where(
                MetricDefinition.framework_version_id == snapshot.framework_version_id,
                MetricDefinition.metric_code == v["metric_code"],
            )
        )
        section = metric.section if metric else "?"
        by_section.setdefault(section, []).append({**v, "label": metric.label if metric else v["metric_code"]})
    principles: dict[str, list[dict]] = {}
    for v in by_section.get("C", []):
        metric = db.scalar(
            select(MetricDefinition).where(
                MetricDefinition.framework_version_id == snapshot.framework_version_id,
                MetricDefinition.metric_code == v["metric_code"],
            )
        )
        p = metric.principle if metric else "?"
        principles.setdefault(p, []).append(v)

    def rows(items):
        out = []
        for v in items:
            val = v["normalized_value"] or v["raw_value"] or "—"
            out.append(
                f"<tr><td class='mono'>{v['metric_code']}</td><td>{v['label']}</td>"
                f"<td class='num'>{val}</td><td>{v['normalized_unit'] or v['raw_unit'] or ''}</td>"
                f"<td>{v['submitted_by'] or ''}</td>"
                f"<td>{'✓' if v['evidence'] else '—'}</td></tr>"
            )
        return "".join(out)

    principle_blocks = "".join(
        f"<h3>Principle {p[1] if p[0] == 'P' else p}</h3><table><thead><tr>"
        "<th>Code</th><th>Indicator</th><th>Value</th><th>Unit</th><th>Submitted by</th><th>Evidence</th>"
        "</tr></thead><tbody>" + rows(items) + "</tbody></table>"
        for p, items in sorted(principles.items())
    )

    consolidated_rows = "".join(
        f"<tr><td class='mono'>{c['metric_code']}</td><td>{c['entity_name']}</td>"
        f"<td>{c['metric_label']}</td><td class='num'>{c['computed_value'] or '—'}</td>"
        f"<td>{c['unit'] or ''}</td><td>{c['aggregation_semantics'] or ''}</td>"
        f"<td>{'Complete' if c['is_complete'] else 'Incomplete'}</td></tr>"
        for c in snapshot.payload.get("consolidated", [])
    )
    consolidated_block = ""
    if consolidated_rows:
        consolidated_block = (
            "<h2>Consolidated Group & Entity KPIs</h2>"
            "<table><thead><tr><th>Code</th><th>Entity</th><th>Indicator</th><th>Consolidated Value</th><th>Unit</th><th>Method</th><th>Status</th></tr></thead>"
            f"<tbody>{consolidated_rows}</tbody></table>"
        )

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
      body {{ font-family: Helvetica, Arial, sans-serif; margin: 36px; color: #12241c; }}
      h1 {{ color: #0b3d2c; letter-spacing: .5px; }} h2 {{ color: #0b3d2c; border-bottom: 2px solid #0b3d2c; padding-bottom: 4px; }}
      h3 {{ color: #0b3d2c; margin-top: 22px; }}
      table {{ width: 100%; border-collapse: collapse; font-size: 10px; margin-top: 8px; }}
      th {{ background: #0b3d2c; color: white; text-align: left; padding: 5px 7px; }}
      td {{ border-bottom: 1px solid #d8e2dc; padding: 4px 7px; }}
      .num {{ text-align: right; }} .mono {{ font-family: monospace; font-size: 9px; }}
      .cover {{ text-align: center; margin: 90px 0 60px; }}
      .checksum {{ font-size: 9px; color: #5c6f66; margin-top: 30px; }}
    </style></head><body>
      <div class="cover">
        <h1>Business Responsibility and Sustainability Report</h1>
        <p style="font-size:14px">Reporting period: <b>{period.label}</b></p>
        <p style="font-size:12px">Generated from immutable snapshot · checksum {snapshot.checksum[:16]}…</p>
      </div>
      {consolidated_block}
      <h2>Section A — General Disclosures</h2>
      <table><thead><tr><th>Code</th><th>Indicator</th><th>Value</th><th>Unit</th><th>Submitted by</th><th>Evidence</th></tr></thead>
      <tbody>{rows(by_section.get("A", []))}</tbody></table>
      <h2>Section B — Management and Process Disclosures</h2>
      <table><thead><tr><th>Code</th><th>Indicator</th><th>Value</th><th>Unit</th><th>Submitted by</th><th>Evidence</th></tr></thead>
      <tbody>{rows(by_section.get("B", []))}</tbody></table>
      <h2>Section C — Principle-wise Performance Disclosures</h2>
      {principle_blocks or "<p>No Section C values in snapshot.</p>"}
      <p class="checksum">Snapshot {snapshot.id} · SHA-256 {snapshot.checksum} · {len(snapshot.payload['values'])} leaf values · {len(snapshot.payload.get('consolidated', []))} consolidated KPIs · generated {datetime.now(UTC).isoformat()}</p>
    </body></html>"""


def render_pdf(db: Session, report: GeneratedReport, html: str) -> str:
    settings = get_settings()
    try:
        from weasyprint import HTML as WeasyHTML

        pdf_bytes = WeasyHTML(string=html).write_pdf()
    except Exception as exc:
        raise ReportingError(f"PDF rendering failed: {exc}", 500)
    object_key = f"reports/{report.period_id}/{report.id}.pdf"
    client = storage.get_client()
    import io

    client.put_object(
        settings.s3_bucket, object_key, io.BytesIO(pdf_bytes),
        length=len(pdf_bytes), content_type="application/pdf",
    )
    return object_key
