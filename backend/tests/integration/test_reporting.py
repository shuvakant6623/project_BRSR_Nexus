"""Reporting-engine integration tests: lock guards, snapshot immutability,
HTML preview and PDF generation (service-level; Celery task is a thin wrapper)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import DEMO_PASSWORD, seed

TEST_STATE: dict = {}


@pytest.fixture(scope="module")
def client(migrated_engine):
    from sqlalchemy.orm import sessionmaker

    from app.db.session import get_db

    TEST_STATE["engine"] = migrated_engine
    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def ctx(migrated_engine):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models import ReportingPeriod

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)
        yield {
            "fy24": db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2024-25")).id,
            "fy25": db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26")).id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_report_generation_refused_for_unlocked_period(client, ctx):
    r = client.post(
        f"/api/v1/reports/{ctx['fy25']}/generate", headers=_login(client, "manager@example.local")
    )
    assert r.status_code == 409
    assert "LOCKED" in r.json()["detail"]


def test_owner_cannot_lock_period(client, ctx):
    r = client.post(
        f"/api/v1/reporting-periods/{ctx['fy24']}/lock",
        headers=_login(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 403


def test_lock_and_generate_report_from_locked_period(client, ctx):
    manager = _login(client, "manager@example.local")

    r = client.post(
        f"/api/v1/reporting-periods/{ctx['fy25']}/lock", headers=manager
    )
    assert r.status_code == 409
    assert "not APPROVED" in r.json()["detail"]

    # FY2024-25 ships pre-locked in the seed (historical period)
    r = client.post(f"/api/v1/reporting-periods/{ctx['fy24']}/lock", headers=manager)
    assert r.status_code == 409 and "already locked" in r.json()["detail"]

    r = client.post(f"/api/v1/reports/{ctx['fy24']}/generate", headers=manager)
    assert r.status_code == 202
    assert len(r.json()["checksum"]) == 64

    # double generation refused: snapshot is immutable
    r = client.post(f"/api/v1/reports/{ctx['fy24']}/generate", headers=manager)
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_html_preview_contains_sections_and_values(client, ctx):
    r = client.get(f"/api/v1/reports/{ctx['fy24']}/preview", headers=_login(client, "management@example.local"))
    assert r.status_code == 200
    html = r.text
    assert "Section A — General Disclosures" in html
    assert "Section C — Principle-wise Performance Disclosures" in html
    assert "Principle 6" in html
    assert "checksum" in html.lower()


def test_pdf_rendered_into_minio(client, ctx):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.infra import storage
    from app.models import GeneratedReport
    from app.reporting.service import render_pdf, render_snapshot_html

    TestSession = sessionmaker(bind=TEST_STATE["engine"], autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        report = db.scalar(select(GeneratedReport).limit(1))
        assert report is not None
        key = render_pdf(db, report, render_snapshot_html(db, report.snapshot_id))
        db.commit()
    stat = storage.get_client().stat_object("brsr-evidence", key)
    assert stat.size > 1000
    with storage.get_client().get_object("brsr-evidence", key) as resp:
        assert resp.read()[:4] == b"%PDF"


# --- regression tests: HTML escaping in preview + readyz dependency naming ---

def test_html_preview_escapes_snapshot_strings(client, ctx):
    """Regression: snapshot-sourced strings used to be interpolated into the
    HTML preview unescaped; they must be entity-escaped (stored-XSS surface).
    Uses FY2025-26, which has no snapshot yet (FY2024-25's is created by the
    lock/generate test and the table admits one snapshot per period)."""
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models import AppUser, MetricDefinition, ReportingPeriod, ReportSnapshot
    from app.reporting.service import render_snapshot_html

    TestSession = sessionmaker(bind=TEST_STATE["engine"], autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        period_id = ctx["fy25"]
        fv_id = db.get(ReportingPeriod, period_id).framework_version_id
        some_user = db.scalar(select(AppUser.id).limit(1))
        real_code = db.scalar(
            select(MetricDefinition.metric_code).where(
                MetricDefinition.framework_version_id == fv_id,
                MetricDefinition.section == "A",
            )
        )
        assert real_code is not None
        payload = {
            "period": "FY2025-26",
            "framework_version_id": str(fv_id),
            "values": [{
                "entity_id": "00000000-0000-0000-0000-000000000000",
                "metric_code": real_code,
                "raw_value": "1",
                "raw_unit": "<b>kWh</b>",
                "normalized_value": None,
                "normalized_unit": None,
                "is_calculated": False,
                "formula_version": None,
                "status": "APPROVED",
                "submitted_by": '<img src=x onerror=alert(1)>@evil.example',
                "submitted_at": None,
                "evidence": [],
            }],
        }
        snapshot = ReportSnapshot(
            period_id=period_id, framework_version_id=fv_id,
            payload=payload, checksum="0" * 64, created_by=some_user,
        )
        db.add(snapshot)
        db.commit()
        html = render_snapshot_html(db, snapshot.id)
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;b&gt;kWh&lt;/b&gt;" in html


def test_readyz_reports_s3_dependency(client):
    """Regression: the object-storage dependency used to be reported under the
    key 'minio' although the storage service is S3-compatible (RustFS)."""
    r = client.get("/readyz")
    assert r.status_code == 200
    deps = r.json()["dependencies"]
    assert "s3" in deps
    assert "minio" not in deps
    assert deps["s3"] is True
