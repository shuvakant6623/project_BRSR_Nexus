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
            "beta": db.scalar(select(Entity).where(Entity.name == "Plant Beta")).id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload_evidence(client, headers, ctx, entity_key="alpha"):
    """Save a draft value + upload evidence on the owner's first editable
    assignment for the entity; returns the metric_value id."""
    rows = client.get(
        f"/api/v1/assignments?entity_id={ctx[entity_key]}&status=IN_PROGRESS",
        headers=headers,
    ).json()
    if not rows:
        rows = client.get(
            f"/api/v1/assignments?entity_id={ctx[entity_key]}&status=NOT_STARTED",
            headers=headers,
        ).json()
    target = rows[0]
    detail = client.get(f"/api/v1/assignments/{target['id']}", headers=headers).json()
    metric = detail["metric"]
    body = {"action": "SAVE_DRAFT", "expected_last_version": detail["latest_version"]}
    if metric["data_type"] == "numeric":
        body["raw_value"] = 3200
        units = metric.get("allowed_units") or ([metric["canonical_unit"]] if metric["canonical_unit"] else [])
        if units:
            body["raw_unit"] = units[0]
    else:
        body["qualitative_value"] = "recorded meter reading for the period"
    saved = client.post(
        f"/api/v1/assignments/{target['id']}/value", json=body, headers=headers,
    )
    assert saved.status_code == 201, saved.json()
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


# --- regression tests: suggestion ownership (IDOR) and list scoping ----------

def test_owner_cannot_extract_from_anothers_evidence(client, ctx):
    """Regression: extraction used to be triggerable by any data owner on any
    evidence; it must be restricted to the assignment's owner (or admin)."""
    alpha_h = _login(client, "owner-alpha@example.local")
    value_id = _upload_evidence(client, alpha_h, ctx)
    evidence = client.get(
        f"/api/v1/evidence/by-value/{value_id}", headers=alpha_h
    ).json()[0]
    beta_h = _login(client, "owner-beta@example.local")
    r = client.post(f"/api/v1/ai-suggestions/extract/{evidence['id']}", headers=beta_h)
    assert r.status_code == 403
    # the owner still can
    assert client.post(
        f"/api/v1/ai-suggestions/extract/{evidence['id']}", headers=alpha_h
    ).status_code == 202


def test_owner_cannot_accept_anothers_suggestion(client, ctx):
    """Regression: accepting used to let any data owner create a draft value on
    an assignment they do not own."""
    alpha_h = _login(client, "owner-alpha@example.local")
    value_id = _upload_evidence(client, alpha_h, ctx)
    evidence = client.get(
        f"/api/v1/evidence/by-value/{value_id}", headers=alpha_h
    ).json()[0]
    client.post(f"/api/v1/ai-suggestions/extract/{evidence['id']}", headers=alpha_h)
    suggestion = next(
        s for s in client.get(
            "/api/v1/ai-suggestions?pending_only=true", headers=alpha_h
        ).json()
        if s["evidence_id"] == evidence["id"]
    )
    beta_h = _login(client, "owner-beta@example.local")
    r = client.post(
        f"/api/v1/ai-suggestions/{suggestion['id']}/accept", json={}, headers=beta_h
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/v1/ai-suggestions/{suggestion['id']}/reject", headers=beta_h
    )
    assert r.status_code == 403
    # alpha can still accept it (creates the draft; double-accept would 409)
    r = client.post(
        f"/api/v1/ai-suggestions/{suggestion['id']}/accept", json={}, headers=alpha_h
    )
    assert r.status_code == 200


def test_suggestion_list_scoped_to_owner(client, ctx):
    """Regression: GET /ai-suggestions used to leak every user's suggestions;
    a data owner now sees only suggestions on their own assignments."""
    alpha_h = _login(client, "owner-alpha@example.local")
    beta_h = _login(client, "owner-beta@example.local")
    # a suggestion on ALPHA's assignment must not appear in BETA's list
    alpha_value = _upload_evidence(client, alpha_h, ctx)
    alpha_evidence = client.get(
        f"/api/v1/evidence/by-value/{alpha_value}", headers=alpha_h
    ).json()[0]
    client.post(f"/api/v1/ai-suggestions/extract/{alpha_evidence['id']}", headers=alpha_h)
    assert all(
        s["evidence_id"] != alpha_evidence["id"]
        for s in client.get("/api/v1/ai-suggestions", headers=beta_h).json()
    )
    # a suggestion on BETA's own assignment does appear
    beta_value = _upload_evidence(client, beta_h, ctx, entity_key="beta")
    beta_evidence = client.get(
        f"/api/v1/evidence/by-value/{beta_value}", headers=beta_h
    ).json()[0]
    client.post(f"/api/v1/ai-suggestions/extract/{beta_evidence['id']}", headers=beta_h)
    beta_id = client.get("/api/v1/auth/me", headers=beta_h).json()["id"]
    mine = client.get("/api/v1/ai-suggestions", headers=beta_h).json()
    assert any(s["evidence_id"] == beta_evidence["id"] for s in mine)
    admin_h = _login(client, "admin@example.local")
    for s in mine:
        assignment = client.get(
            f"/api/v1/assignments/{s['assignment_id']}", headers=admin_h
        ).json()["assignment"]
        assert assignment["owner_user_id"] == beta_id
