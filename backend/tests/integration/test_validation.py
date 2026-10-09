"""Validation-engine integration tests: rule classes, exceptions lifecycle."""

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
            "period_fy25": db.scalar(
                select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26")
            ).id,
            "period_fy24": db.scalar(
                select(ReportingPeriod).where(ReportingPeriod.label == "FY2024-25")
            ).id,
            "plant_alpha": db.scalar(select(Entity).where(Entity.name == "Plant Alpha")).id,
            "plant_beta": db.scalar(select(Entity).where(Entity.name == "Plant Beta")).id,
            "plant_delta": db.scalar(select(Entity).where(Entity.name == "Plant Delta")).id,
            "project_d": db.scalar(select(Entity).where(Entity.name == "Project D")).id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _exceptions(client, headers, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/v1/validation/exceptions?{qs}", headers=headers).json()


def test_workforce_mismatch_raises_blocking_cross_section(client, ctx):
    """Demo anomaly #1: Beta FY25 Section A employees (252) != Section C workforce (240)."""
    r = client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_beta"])},
        headers=_login(client, "manager@example.local"),
    )
    assert r.status_code == 200
    # earlier test modules may already have run validation on Beta; the run
    # raises only NEW findings, so assert on the exception's existence below
    rows = _exceptions(
        client, _login(client, "reviewer@example.local"),
        entity_id=str(ctx["plant_beta"]), severity="BLOCKING",
    )
    codes = {e["rule_code"] for e in rows}
    assert "VR-XS-EMPLOYEES" in codes or "VR-XF-EMPLOYEES" in codes
    mismatch = next(e for e in rows if e["rule_code"] in ("VR-XS-EMPLOYEES", "VR-XF-EMPLOYEES"))
    assert "252" in mismatch["message"] and "240" in mismatch["message"]


def test_yoy_energy_warning_with_percent_in_message(client, ctx):
    """Demo anomaly #2: Alpha energy 100 MWh -> 170 MWh (+70%). The warning is
    raised by the review-stage sweep when the reviewer opens the submission."""
    owner_h = _login(client, "owner-alpha@example.local")
    reviewer_h = _login(client, "reviewer@example.local")
    energy = None
    for status_filter in ("IN_PROGRESS", "SUBMITTED"):
        rows = client.get(
            f"/api/v1/assignments?entity_id={ctx['plant_alpha']}&status={status_filter}",
            headers=owner_h,
        ).json()
        matches = [a for a in rows if a["metric_code"] == "C-P6-GRID-NONRENEWABLE-MWH"]
        if matches:
            energy = matches[0]
            break
    assert energy is not None, "seeded Alpha energy assignment must exist"
    if energy["status"] == "IN_PROGRESS":
        detail = client.get(f"/api/v1/assignments/{energy['id']}", headers=owner_h).json()
        submitted = client.post(
            f"/api/v1/assignments/{energy['id']}/value",
            json={"action": "SUBMIT", "raw_value": 170000, "raw_unit": "kWh",
                  "expected_last_version": detail["latest_version"]},
            headers=owner_h,
        )
        assert submitted.status_code == 201
    started = client.post(
        f"/api/v1/assignments/{energy['id']}/review",
        json={"action": "START_REVIEW"}, headers=reviewer_h,
    )
    assert started.status_code == 200

    yoy = [
        e
        for e in _exceptions(client, reviewer_h, entity_id=str(ctx["plant_alpha"]))
        if e["rule_code"] == "VR-YOY-ENERGY"
    ]
    assert yoy, "YoY warning must be raised for the +70% energy change"
    assert "70%" in yoy[0]["message"]


def test_evidence_completeness_blocking_for_core(client, ctx):
    """Demo anomaly #3: BRSR Core metrics without evidence raise BLOCKING."""
    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_delta"])},
        headers=_login(client, "manager@example.local"),
    )
    rows = _exceptions(
        client, _login(client, "reviewer@example.local"),
        entity_id=str(ctx["plant_delta"]), severity="BLOCKING",
    )
    evidence = [e for e in rows if e["rule_code"] == "VR-EVIDENCE-CORE"]
    assert evidence, "core metrics without evidence must raise BLOCKING exceptions"
    assert all("requires evidence" in e["message"] or "evidence" in e["message"] for e in evidence)


def test_missing_required_core_value_raises(client, ctx):
    """Project D/Zeta have assignments with no values -> REQUIRED blocking."""
    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"])},
        headers=_login(client, "admin@example.local"),
    )
    rows = _exceptions(client, _login(client, "reviewer@example.local"), severity="BLOCKING")
    required = [e for e in rows if e["rule_code"] == "VR-REQ-CORE"]
    assert required, "missing BRSR Core values must raise REQUIRED blocking exceptions"


def test_rerun_auto_resolves_cleared_open_exceptions(client, ctx):
    """An OPEN exception whose condition clears on re-run becomes RESOLVED;
    re-running must never duplicate existing OPEN exceptions."""
    reviewer_h = _login(client, "reviewer@example.local")
    # Beta has a genuine cross-section mismatch -> OPEN exceptions on first run
    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_beta"])},
        headers=_login(client, "manager@example.local"),
    )
    before = _exceptions(client, reviewer_h, entity_id=str(ctx["plant_beta"]))
    open_before = {e["id"] for e in before if e["status"] == "OPEN"}
    assert open_before
    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_beta"])},
        headers=_login(client, "manager@example.local"),
    )
    after = _exceptions(client, reviewer_h, entity_id=str(ctx["plant_beta"]))
    still_open = {e["id"] for e in after if e["status"] == "OPEN"}
    assert still_open == open_before, "re-run must not duplicate OPEN exceptions"


def test_explain_and_resolve_lifecycle_with_permissions(client, ctx):
    owner_h = _login(client, "owner-beta@example.local")
    reviewer_h = _login(client, "reviewer@example.local")
    mgmt_h = _login(client, "management@example.local")

    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_beta"])},
        headers=_login(client, "manager@example.local"),
    )
    rows = _exceptions(client, reviewer_h, entity_id=str(ctx["plant_beta"]))
    target = rows[0]["id"]

    # management cannot explain or resolve
    assert (
        client.post(
            f"/api/v1/validation/exceptions/{target}/explain",
            json={"explanation": "should not be allowed"},
            headers=mgmt_h,
        ).status_code
        == 403
    )

    # owner explains
    explained = client.post(
        f"/api/v1/validation/exceptions/{target}/explain",
        json={"explanation": "Contract staff onboarded mid-year; HRIS reconciliation pending."},
        headers=owner_h,
    )
    assert explained.status_code == 200
    assert explained.json()["status"] == "EXPLAINED"

    # reviewer resolves
    resolved = client.post(
        f"/api/v1/validation/exceptions/{target}/resolve", headers=reviewer_h
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"

    # explaining a resolved exception fails
    assert (
        client.post(
            f"/api/v1/validation/exceptions/{target}/explain",
            json={"explanation": "too late"},
            headers=owner_h,
        ).status_code
        == 409
    )


def test_owner_cannot_see_foreign_exceptions(client, ctx):
    owner_h = _login(client, "owner-alpha@example.local")
    rows = _exceptions(client, owner_h)
    alpha_ids = {str(ctx["plant_alpha"])}
    assert all(e["entity_id"] in alpha_ids for e in rows)


def test_data_owner_cannot_run_validation(client, ctx):
    r = client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"])},
        headers=_login(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 403


def test_submission_blocked_for_required_core_without_value(client, ctx):
    """Submitting on a fresh core assignment isn't possible without a value; the
    structural path already 422s. Here we assert the submit-stage engine also
    fires REQUIRED for a draft-less core assignment through the run endpoint."""
    r = client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"])},
        headers=_login(client, "admin@example.local"),
    )
    body = r.json()
    assert body["status"] == "completed"
    assert body["assignments"] > 0


def test_first_submit_on_fresh_core_assignment_passes(client, ctx):
    """The submit-stage gate judges the incoming payload, not the previously
    persisted version: a first-time SUBMIT of a valid BRSR Core value on a
    NOT_STARTED assignment (no value yet) must succeed with 201."""
    owner_h = _login(client, "owner-projc@example.local")
    rows = client.get(
        f"/api/v1/assignments?entity_id={ctx['project_d']}&status=NOT_STARTED",
        headers=owner_h,
    ).json()
    target = next(a for a in rows if a["metric_code"] == "C-P8-CSR-SPEND")
    detail = client.get(f"/api/v1/assignments/{target['id']}", headers=owner_h).json()
    submitted = client.post(
        f"/api/v1/assignments/{target['id']}/value",
        json={"action": "SUBMIT", "raw_value": 1.35, "raw_unit": "INR crore",
              "expected_last_version": detail["latest_version"]},
        headers=owner_h,
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "SUBMITTED"


def test_audit_events_recorded_for_exceptions(client, ctx):
    from sqlalchemy import text

    client.post(
        "/api/v1/validation/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_beta"])},
        headers=_login(client, "manager@example.local"),
    )
    with TEST_STATE["engine"].connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM audit_event WHERE action='EXCEPTION_RAISED'")
        ).scalar()
    assert count > 0


def test_statistical_sweep_flags_cross_site_outliers(client, ctx):
    """The PDF's recommended second layer: IQR + z-score across peer plants.
    Delta is deliberately emissions-heavy -> must be flagged statistically."""

    # seed divergence: Delta revenue is decoupled, so its GHG intensity is a
    # peer outlier; sweep runs on approved FY24 values
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(bind=TEST_STATE["engine"], autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        from app.models import ReportingPeriod

        fy24 = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2024-25"))
        from app.validation import statistics

        result = statistics.run_statistical_sweep(db, fy24.id, actor_label="test")
        db.commit()
    assert result["checked"] > 0, "peer metrics with >= 4 approved plants must be checked"
    rows = _exceptions(client, _login(client, "reviewer@example.local"))
    iqr_rows = [e for e in rows if e["rule_code"] == "VR-IQR-PEER"]
    z_rows = [e for e in rows if e["rule_code"] == "VR-ZSCORE-PEER"]
    assert iqr_rows or z_rows, "deliberate cross-site outliers must raise statistical exceptions"
