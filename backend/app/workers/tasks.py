"""Celery task definitions. Each returns a structured result and records
failures explicitly — no silent failures (spec §16/§24)."""
import logging
import uuid

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def generate_report(self, report_id: str) -> dict:
    """Render the immutable snapshot into HTML + PDF and store in MinIO."""
    from datetime import UTC, datetime

    from app.db.session import SessionLocal
    from app.models import GeneratedReport
    from app.reporting.service import render_pdf, render_snapshot_html

    db = SessionLocal()
    try:
        report = db.get(GeneratedReport, uuid.UUID(report_id))
        if report is None:
            raise RuntimeError(f"report {report_id} not found")
        report.status = "RUNNING"
        report.started_at = datetime.now(UTC)
        db.commit()

        html = render_snapshot_html(db, report.snapshot_id)
        object_key = render_pdf(db, report, html)

        report.status = "SUCCESS"
        report.file_object_key = object_key
        report.completed_at = datetime.now(UTC)
        db.commit()
        return {"report_id": report_id, "status": "SUCCESS", "object_key": object_key}
    except Exception as exc:
        db.rollback()
        report = db.get(GeneratedReport, uuid.UUID(report_id))
        if report is not None:
            report.retry_count = self.request.retries
            if self.request.retries >= (self.max_retries or 0):
                report.status = "FAILED"
                report.error = str(exc)[:2000]
                report.completed_at = datetime.now(UTC)
            db.commit()
        logger.exception("report generation failed for %s", report_id)
        if self.request.retries < (self.max_retries or 0):
            raise self.retry(exc=exc)
        return {"report_id": report_id, "status": "FAILED", "error": str(exc)}
    finally:
        db.close()


@celery_app.task
def scan_reminders() -> dict:
    """Celery Beat scan (spec §22): due-soon / overdue notifications."""
    from app.notifications.router import scan_reminders as _scan

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return _scan(db)
    finally:
        db.close()
