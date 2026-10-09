"""Bulk-import integration tests (spec §21)."""
import io
import uuid

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

    from app.models import Entity, ReportingPeriod

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)
        yield {
            "fy24": db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2024-25")).id,
            "fy25": db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26")).id,
            "alpha": db.scalar(select(Entity).where(Entity.name == "Plant Alpha")).id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_template_lists_owned_assignments(client, ctx):
    r = client.get("/api/v1/bulk-import/template", headers=_login(client, "owner-alpha@example.local"))
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0] == "metric_code,entity_name,value,unit"
    assert any("Plant Alpha" in ln for ln in lines[1:])


def test_bulk_import_creates_drafts_never_submitted(client, ctx):
    csv_content = (
        "metric_code,entity_name,value,unit\n"
        "C-P6-WATER-DISCHARGE,Plant Alpha,3100,kL\n"
        "C-P6-WASTE-RECYCLED,Plant Alpha,42,tonne\n"
        "C-P6-WATER-DISCHARGE,Plant Nowhere,999,kL\n"
        "C-P6-WATER-DISCHARGE,Plant Alpha,notanumber,kL\n"
    )
    r = client.post(
        "/api/v1/bulk-import",
        params={"period_id": str(ctx["fy25"])},
        files={"file": ("import.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        headers=_login(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # process synchronously (Celery task body is a thin wrapper)
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.imports.service import process_import
    from app.models import AppUser, BulkImportJob

    TestSession = sessionmaker(bind=TEST_STATE["engine"], autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        user = db.scalar(select(AppUser).where(AppUser.email == "owner-alpha@example.local"))
        result = process_import(db, uuid.UUID(job_id), user.id)
        db.commit()
    assert result["total"] == 4
    assert result["valid"] == 2
    assert result["invalid"] == 2

    # imported rows are IN_PROGRESS drafts, never SUBMITTED
    with TestSession() as db:
        job = db.get(BulkImportJob, uuid.UUID(job_id))
        assert job.status.value == "SUCCESS"
        assert job.error_report_object_key is not None
    status = client.get(f"/api/v1/bulk-import/{job_id}", headers=_login(client, "owner-alpha@example.local")).json()
    assert status["valid_rows"] == 2 and status["invalid_rows"] == 2


def test_import_requires_csv(client, ctx):
    r = client.post(
        "/api/v1/bulk-import",
        params={"period_id": str(ctx["fy25"])},
        files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
        headers=_login(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 422


def test_foreign_job_hidden(client, ctx):
    r = client.get(f"/api/v1/bulk-import/{uuid.uuid4()}", headers=_login(client, "owner-beta@example.local"))
    assert r.status_code == 404


# --- regression tests: upload-time period validation -------------------------

def test_import_unknown_period_rejected_404(client, ctx):
    """Regression: an import against a nonexistent period used to be accepted
    (202) and only fail later, row by row."""
    r = client.post(
        "/api/v1/bulk-import",
        params={"period_id": str(uuid.uuid4())},
        files={"file": ("import.csv", io.BytesIO(b"metric_code,entity_name,value,unit\n"), "text/csv")},
        headers=_login(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 404


def test_import_locked_period_rejected_409(client, ctx):
    """Regression: imports against a locked period must be refused outright.
    FY2024-25 ships pre-locked in the seed (historical period)."""
    r = client.post(
        "/api/v1/bulk-import",
        params={"period_id": str(ctx["fy24"])},
        files={"file": ("import.csv", io.BytesIO(b"metric_code,entity_name,value,unit\n"), "text/csv")},
        headers=_login(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 409
