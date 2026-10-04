"""AI/OCR suggestion tests (spec §23, research §9.2): draft-only flow,
human-in-the-loop, never auto-submitted/approved/locked."""
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
            "fy25": db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26")).id,
            "alpha": db.scalar(select(Entity).where(Entity.name == "Plant Alpha")).id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload_evidence(client, headers, ctx):
    from datetime import date

    # create a value + evidence via API on a non-core metric
    rows = client.get(
        f"/api/v1/assignments?entity_id={ctx['alpha']}&status=IN_PROGRESS",
        headers=headers,
    ).json()
    target = next(a for a in rows if a["metric_code"] == "C-P6-WATER-DISCHARGE")
    detail = client.get(f"/api/v1/assignments/{target['id']}", headers=headers).json()
    saved = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SAVE_DRAFT", "raw_value": 3200, "raw_unit": "kL",
              "expected_last_version": detail["latest_version"]},
        headers=headers,
    )
    assert saved.status_code == 201
    up = client.post(
        "/api/v1/evidence",
        params={"metric_value_id": saved.json()["id"]},
        files={"file": ("water_reading.csv",
                        b"meter_reading for March 2025\ntotal consumed: 3250 KL",
                        "text/csv")},
        headers=headers,
    )
    assert up.status_code == 201, up.json()
    return saved.json()["id"]


def test_extraction_creates_pending_suggestion(client, ctx):
    owner_h = _login(client, "owner-alpha@example.local")
    value_id = _upload_evidence(client, owner_h, ctx)
    evidence = client.get(
        f"/api/v1/evidence/by-value/{value_id}", headers=owner_h
    ).json()[0]
    r = client.post(f"/api/v1/ai-suggestions/extract/{evidence['id']}", headers=owner_h)
    assert r.status_code == 202
    assert r.json()["provider"] == "local_demo"
    suggestions = client.get(
        "/api/v1/ai-suggestions?pending_only=true", headers=owner_h
    ).json()
    assert any(s["evidence_id"] == evidence["id"] for s in suggestions)


def test_accept_creates_owner_draft_never_submitted(client, ctx):
    owner_h = _login(client, "owner-alpha@example.local")
    suggestions = client.get(
        "/api/v1/ai-suggestions?pending_only=true", headers=owner_h
    ).json()
    target = suggestions[0]
    r = client.post(
        f"/api/v1/ai-suggestions/{target['id']}/accept",
        json={"value": 3250, "unit": "kL"},
        headers=owner_h,
    )
    assert r.status_code == 200
    detail = client.get(
        f"/api/v1/assignments/{target['assignment_id']}", headers=owner_h
    ).json()
    latest = detail["values"][0]
    # THE invariant: AI acceptance produces an IN_PROGRESS draft owned by the
    # data owner — never SUBMITTED / APPROVED / LOCKED
    assert latest["status"] == "IN_PROGRESS"
    assert float(latest["raw_value"]) == 3250
    assert detail["assignment"]["status"] == "IN_PROGRESS"

    # double-accept refused
    r = client.post(
        f"/api/v1/ai-suggestions/{target['id']}/accept", json={}, headers=owner_h
    )
    assert r.status_code == 409


def test_reviewer_cannot_accept_suggestions(client, ctx):
    r = client.post(
        f"/api/v1/ai-suggestions/{uuid.uuid4()}/accept", json={},
        headers=_login(client, "reviewer@example.local"),
    )
    assert r.status_code == 403


def test_demo_provider_is_labelled(client, ctx):
    from app.ai.service import get_provider

    provider = get_provider()
    assert provider.name == "local_demo"
    candidates = provider.extract("bill.txt", b"Total consumed: 1,234 kWh")
    assert candidates and candidates[0]["unit"] == "kWh"
