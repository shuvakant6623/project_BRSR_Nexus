"""Collection integration tests: state machine, versioning, guards, RBAC."""
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

    from app.models import AppUser, Entity, FrameworkVersion, ReportingPeriod

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)
        ctx = {
            "fv_current": db.scalar(
                select(FrameworkVersion).where(FrameworkVersion.version_code == "BRSR-FY2025-26")
            ).id,
            "period_fy25": db.scalar(
                select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26")
            ).id,
            "period_fy24": db.scalar(
                select(ReportingPeriod).where(ReportingPeriod.label == "FY2024-25")
            ).id,
            "plant_alpha": db.scalar(select(Entity).where(Entity.name == "Plant Alpha")).id,
            "plant_beta": db.scalar(select(Entity).where(Entity.name == "Plant Beta")).id,
            "owner_alpha": db.scalar(
                select(AppUser).where(AppUser.email == "owner-alpha@example.local")
            ).id,
        }
        yield ctx


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _assignments(client, headers, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/v1/assignments?{qs}", headers=headers).json()


def test_owner_sees_only_own_assignments(client, ctx):
    rows = _assignments(client, _login(client, "owner-alpha@example.local"))
    assert rows, "owner-alpha should have assignments"
    assert all(a["owner_user_id"] == str(ctx["owner_alpha"]) for a in rows)


def test_owner_cannot_access_foreign_assignment_detail(client, ctx):
    beta_rows = _assignments(
        client, _login(client, "owner-beta@example.local"), entity_id=str(ctx["plant_beta"])
    )
    target = beta_rows[0]["id"]
    r = client.get(
        f"/api/v1/assignments/{target}", headers=_login(client, "owner-alpha@example.local")
    )
    assert r.status_code == 403


def test_draft_save_then_submit_flow(client, ctx):
    headers = _login(client, "owner-alpha@example.local")
    rows = _assignments(
        client, headers, entity_id=str(ctx["plant_alpha"]), status="IN_PROGRESS"
    )
    target = next(a for a in rows if a["metric_code"] == "C-P6-GRID-RENEWABLE-MWH")
    detail = client.get(f"/api/v1/assignments/{target['id']}", headers=headers).json()
    last_version = detail["latest_version"] or 0

    draft = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SAVE_DRAFT", "raw_value": 28.0, "raw_unit": "MWh",
              "expected_last_version": last_version},
        headers=headers,
    )
    assert draft.status_code == 201
    assert draft.json()["status"] == "IN_PROGRESS"
    assert draft.json()["version"] == last_version + 1

    submitted = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SUBMIT", "raw_value": 30.0, "raw_unit": "MWh",
              "expected_last_version": draft.json()["version"]},
        headers=headers,
    )
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "SUBMITTED"

    detail_after = client.get(f"/api/v1/assignments/{target['id']}", headers=headers).json()
    assert detail_after["assignment"]["status"] == "SUBMITTED"
    assert len(detail_after["values"]) == last_version + 2  # history preserved
    assert detail_after["values"][0]["version"] > detail_after["values"][-1]["version"]


def test_submit_requires_value_and_valid_unit(client, ctx):
    headers = _login(client, "owner-alpha@example.local")
    rows = _assignments(client, headers, entity_id=str(ctx["plant_alpha"]), status="IN_PROGRESS")
    target = next(a for a in rows if a["metric_code"] == "C-P6-WATER-WITHDRAWAL")

    bad_unit = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SUBMIT", "raw_value": 1.0, "raw_unit": "bogus_unit"},
        headers=headers,
    )
    assert bad_unit.status_code == 422

    missing = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SUBMIT", "raw_value": None, "raw_unit": "kL"},
        headers=headers,
    )
    assert missing.status_code == 422


def test_concurrent_edit_conflict(client, ctx):
    headers = _login(client, "owner-alpha@example.local")
    rows = _assignments(client, headers, entity_id=str(ctx["plant_alpha"]), status="IN_PROGRESS")
    target = rows[0]
    stale = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SAVE_DRAFT", "raw_value": 1.0, "expected_last_version": 99},
        headers=headers,
    )
    assert stale.status_code == 409


def test_full_review_lifecycle(client, ctx):
    owner_h = _login(client, "owner-gamma@example.local")
    reviewer_h = _login(client, "reviewer@example.local")
    # pick a SUBMITTED assignment owned by owner-gamma (she owns Plant Gamma)
    gamma_rows = _assignments(client, owner_h, status="SUBMITTED")
    assert gamma_rows, "seeded SUBMITTED assignments for Plant Gamma must exist"
    target_id = gamma_rows[0]["id"]

    started = client.post(
        f"/api/v1/assignments/{target_id}/review",
        json={"action": "START_REVIEW"}, headers=reviewer_h,
    )
    assert started.status_code == 200
    assert started.json()["status"] == "UNDER_REVIEW"

    # reject without comment -> 422
    rejected = client.post(
        f"/api/v1/assignments/{target_id}/review",
        json={"action": "REJECT"}, headers=reviewer_h,
    )
    assert rejected.status_code == 422

    # needs correction with comment, then owner fixes, resubmits, approve
    nc = client.post(
        f"/api/v1/assignments/{target_id}/review",
        json={"action": "NEEDS_CORRECTION", "comment": "Please verify the reading"},
        headers=reviewer_h,
    )
    assert nc.status_code == 200 and nc.json()["status"] == "NEEDS_CORRECTION"

    detail = client.get(f"/api/v1/assignments/{target_id}", headers=owner_h).json()
    # owner saves again after correction -> IN_PROGRESS
    saved = client.post(
        f"/api/v1/assignments/{target_id}/value",
        json={"action": "SAVE_DRAFT", "raw_value": 42.0,
              "expected_last_version": detail["latest_version"]},
        headers=owner_h,
    )
    assert saved.status_code == 201
    resubmitted = client.post(
        f"/api/v1/assignments/{target_id}/value",
        json={"action": "SUBMIT", "raw_value": 43.0, "raw_unit": detail["metric"]["allowed_units"][0] if detail["metric"]["allowed_units"] else None,
              "expected_last_version": saved.json()["version"]},
        headers=owner_h,
    )
    assert resubmitted.status_code == 201

    client.post(f"/api/v1/assignments/{target_id}/review",
                json={"action": "START_REVIEW"}, headers=reviewer_h)
    approved = client.post(
        f"/api/v1/assignments/{target_id}/review",
        json={"action": "APPROVE"}, headers=reviewer_h,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


def test_owner_cannot_review(client, ctx):
    owner_h = _login(client, "owner-alpha@example.local")
    rows = _assignments(client, owner_h, status="SUBMITTED")
    if not rows:
        pytest.skip("no submitted assignments visible to owner")
    r = client.post(
        f"/api/v1/assignments/{rows[0]['id']}/review",
        json={"action": "START_REVIEW"}, headers=owner_h,
    )
    assert r.status_code == 403


def test_management_cannot_edit_values(client, ctx):
    mgmt_h = _login(client, "management@example.local")
    rows = _assignments(client, mgmt_h, status="IN_PROGRESS")
    if not rows:
        pytest.skip("no in-progress assignments visible to management")
    r = client.post(
        f"/api/v1/assignments/{rows[0]['id']}/value",
        json={"action": "SAVE_DRAFT", "raw_value": 1.0},
        headers=mgmt_h,
    )
    assert r.status_code == 403


def test_locked_period_rejects_value_save(client, ctx):
    owner_h = _login(client, "owner-alpha@example.local")
    rows = _assignments(client, owner_h, period_id=str(ctx["period_fy24"]))
    assert rows, "FY24 assignments should exist"
    r = client.post(
        f"/api/v1/assignments/{rows[0]['id']}/value",
        json={"action": "SAVE_DRAFT", "raw_value": 1.0},
        headers=owner_h,
    )
    assert r.status_code == 409
    assert "locked" in r.json()["detail"].lower()


def test_duplicate_assignment_rejected(client, ctx):
    manager_h = _login(client, "manager@example.local")
    rows = _assignments(client, manager_h, entity_id=str(ctx["plant_alpha"]), status="IN_PROGRESS")
    target = rows[0]
    r = client.post(
        "/api/v1/assignments",
        json={
            "metric_code": target["metric_code"],
            "entity_id": target["entity_id"],
            "period_id": target["period_id"],
            "owner_user_id": target["owner_user_id"],
        },
        headers=manager_h,
    )
    assert r.status_code == 409


def test_assignment_for_metric_not_in_period_framework_rejected(client, ctx):
    manager_h = _login(client, "manager@example.local")
    r = client.post(
        "/api/v1/assignments",
        json={
            # only exists in the FY25 framework, assign against FY24 period
            "metric_code": "C-P6-WATER-DISCHARGE",
            "entity_id": str(ctx["plant_alpha"]),
            "period_id": str(ctx["period_fy24"]),
            "owner_user_id": str(ctx["owner_alpha"]),
        },
        headers=manager_h,
    )
    assert r.status_code == 409


def test_value_history_never_overwritten(client, ctx):
    owner_h = _login(client, "owner-alpha@example.local")
    rows = _assignments(client, owner_h, entity_id=str(ctx["plant_alpha"]))
    with_history = [
        a for a in rows if a["metric_code"] == "C-P6-GRID-RENEWABLE-MWH"
    ]
    detail = client.get(
        f"/api/v1/assignments/{with_history[0]['id']}", headers=owner_h
    ).json()
    versions = [v["version"] for v in detail["values"]]
    assert versions == sorted(versions, reverse=True)
    assert len(set(versions)) == len(versions)


def test_value_save_normalizes_units(client, ctx):
    """170,000 kWh entered in the demo flow normalizes to 170 MWh."""
    owner_h = _login(client, "owner-alpha@example.local")
    rows = _assignments(client, owner_h, entity_id=str(ctx["plant_alpha"]), status="IN_PROGRESS")
    target = next(a for a in rows if a["metric_code"] == "C-P6-GRID-NONRENEWABLE-MWH")
    detail = client.get(f"/api/v1/assignments/{target['id']}", headers=owner_h).json()
    saved = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SUBMIT", "raw_value": 170000, "raw_unit": "kWh",
              "expected_last_version": detail["latest_version"]},
        headers=owner_h,
    )
    assert saved.status_code == 201
    assert saved.json()["raw_value"] == 170000
    assert saved.json()["raw_unit"] == "kWh"
    assert saved.json()["normalized_value"] == 170.0
    assert saved.json()["normalized_unit"] == "MWh"
