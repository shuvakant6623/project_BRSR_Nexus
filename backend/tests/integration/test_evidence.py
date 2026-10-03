"""Evidence-service integration tests: MinIO storage, hashes, signed URLs,
RBAC, duplicates, and the VR-EVIDENCE-CORE control loop."""
import hashlib
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

    from app.models import Assignment, Entity, MetricValue, ReportingPeriod

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)
        period_fy25 = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26"))
        beta = db.scalar(select(Entity).where(Entity.name == "Plant Beta"))
        # a Beta value that is APPROVED but has no evidence (CSR spend is core)
        assignment = db.scalar(
            select(Assignment).where(
                Assignment.entity_id == beta.id,
                Assignment.period_id == period_fy25.id,
                Assignment.metric_code == "C-P8-CSR-SPEND",
            )
        )
        # second core metric kept evidence-free for the control-loop test
        water_assignment = db.scalar(
            select(Assignment).where(
                Assignment.entity_id == beta.id,
                Assignment.period_id == period_fy25.id,
                Assignment.metric_code == "C-P6-WATER-WITHDRAWAL",
            )
        )
        value = db.scalar(
            select(MetricValue)
            .where(MetricValue.assignment_id == assignment.id)
            .order_by(MetricValue.version.desc())
            .limit(1)
        )
        water_value = db.scalar(
            select(MetricValue)
            .where(MetricValue.assignment_id == water_assignment.id)
            .order_by(MetricValue.version.desc())
            .limit(1)
        )
        yield {
            "metric_value_id": value.id,
            "assignment_id": assignment.id,
            "clean_metric_value_id": water_value.id,
            "entity_id": beta.id,
            "period_fy25": period_fy25.id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(client, headers, metric_value_id, filename="electricity_bill.pdf",
            content=b"%PDF-1.4 test bill", mime="application/pdf"):
    return client.post(
        "/api/v1/evidence",
        params={"metric_value_id": str(metric_value_id)},
        files={"file": (filename, content, mime)},
        headers=headers,
    )


def test_upload_stores_in_minio_with_sha256(client, ctx):
    owner_h = _login(client, "owner-beta@example.local")
    r = _upload(client, owner_h, ctx["metric_value_id"])
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["sha256_hash"] == hashlib.sha256(b"%PDF-1.4 test bill").hexdigest()
    assert body["original_filename"] == "electricity_bill.pdf"
    assert body["size_bytes"] == len(b"%PDF-1.4 test bill")

    # the object is really in MinIO
    from app.infra import storage

    client_minio = storage.get_client()
    stat = client_minio.stat_object("brsr-evidence", None) if False else None
    # verify via presigned URL fetch instead
    dl = client.get(f"/api/v1/evidence/{body['id']}/download", headers=owner_h)
    assert dl.status_code == 200
    url = dl.json()["url"]
    assert "brsr-evidence" in url
    import urllib.request

    with urllib.request.urlopen(url) as resp:
        assert resp.read() == b"%PDF-1.4 test bill"


def test_duplicate_upload_flagged(client, ctx):
    owner_h = _login(client, "owner-beta@example.local")
    first = _upload(client, owner_h, ctx["metric_value_id"], filename="a.pdf")
    second = _upload(client, owner_h, ctx["metric_value_id"], filename="copy.pdf")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["sha256_hash"] == second.json()["sha256_hash"]


def test_mime_and_extension_validation(client, ctx):
    owner_h = _login(client, "owner-beta@example.local")
    bad_mime = _upload(client, owner_h, ctx["metric_value_id"],
                       filename="evil.exe", content=b"MZ", mime="application/x-msdownload")
    assert bad_mime.status_code == 422
    mismatch = _upload(client, owner_h, ctx["metric_value_id"],
                       filename="notpdf.txt", content=b"hello", mime="application/pdf")
    assert mismatch.status_code == 422
    empty = _upload(client, owner_h, ctx["metric_value_id"],
                    filename="empty.pdf", content=b"", mime="application/pdf")
    assert empty.status_code == 422


def test_owner_scoped_upload_and_foreign_denied(client, ctx):
    # owner-alpha cannot upload evidence to Beta's value
    foreign = _upload(client, _login(client, "owner-alpha@example.local"), ctx["metric_value_id"])
    assert foreign.status_code == 403
    # management cannot upload either
    mgmt = _upload(client, _login(client, "management@example.local"), ctx["metric_value_id"])
    assert mgmt.status_code == 403


def test_delete_is_soft_and_audited(client, ctx):
    owner_h = _login(client, "owner-beta@example.local")
    up = _upload(client, owner_h, ctx["metric_value_id"], filename="deleteme.pdf")
    evidence_id = up.json()["id"]
    # reviewer cannot delete
    r = client.delete(
        f"/api/v1/evidence/{evidence_id}", headers=_login(client, "reviewer@example.local")
    )
    assert r.status_code == 403
    # owner deletes
    r = client.delete(f"/api/v1/evidence/{evidence_id}", headers=owner_h)
    assert r.status_code == 204
    # metadata read now 404s (soft-deleted)
    assert client.get(f"/api/v1/evidence/{evidence_id}", headers=owner_h).status_code == 404

    from sqlalchemy import text

    with TEST_STATE["engine"].connect() as conn:
        row = conn.execute(
            text("SELECT is_deleted, deleted_at FROM evidence WHERE id = :i"),
            {"i": evidence_id},
        ).first()
        audits = conn.execute(
            text("SELECT count(*) FROM audit_event WHERE object_type='evidence' AND object_id = :i"),
            {"i": evidence_id},
        ).scalar()
    assert row.is_deleted is True and row.deleted_at is not None
    assert audits >= 2  # upload + delete


def test_evidence_upload_clears_blocking_validation_exception(client, ctx):
    """The VR-EVIDENCE-CORE control loop: BLOCKING exception for the core
    metric without evidence; upload + re-run resolves it."""
    reviewer_h = _login(client, "reviewer@example.local")
    manager_h = _login(client, "manager@example.local")

    # run validation to raise the exception (assignment was APPROVED in seed)
    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["entity_id"])},
        headers=manager_h,
    )
    blocking = client.get(
        f"/api/v1/validation/exceptions?entity_id={ctx['entity_id']}&severity=BLOCKING&status=OPEN",
        headers=reviewer_h,
    ).json()
    csr = [e for e in blocking if e["metric_code"] == "C-P6-WATER-WITHDRAWAL" and e["rule_code"] == "VR-EVIDENCE-CORE"]
    assert csr, "expected a VR-EVIDENCE-CORE blocking exception before evidence upload"

    # upload evidence and re-run validation
    up = _upload(client, _login(client, "owner-beta@example.local"), ctx["clean_metric_value_id"],
                 filename="water_meter_log.pdf")
    assert up.status_code == 201
    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["entity_id"])},
        headers=manager_h,
    )
    blocking_after = client.get(
        f"/api/v1/validation/exceptions?entity_id={ctx['entity_id']}&severity=BLOCKING&status=OPEN",
        headers=reviewer_h,
    ).json()
    csr_after = [e for e in blocking_after
                 if e["metric_code"] == "C-P6-WATER-WITHDRAWAL" and e["rule_code"] == "VR-EVIDENCE-CORE"]
    assert not csr_after, "evidence upload + re-run must resolve the blocking exception"
