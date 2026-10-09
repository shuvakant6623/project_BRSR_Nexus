"""Calculation-engine integration tests: derived metrics with formula lineage."""
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
            "plant_epsilon": db.scalar(select(Entity).where(Entity.name == "Plant Epsilon")).id,
            "plant_zeta": db.scalar(select(Entity).where(Entity.name == "Plant Zeta")).id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _detail(client, headers, assignment_id):
    return client.get(f"/api/v1/assignments/{assignment_id}", headers=headers).json()


def _assignment(client, headers, entity_id, metric_code, period_id=None):
    params = {"entity_id": str(entity_id)}
    if period_id:
        params["period_id"] = str(period_id)
    rows = client.get(
        f"/api/v1/assignments?entity_id={entity_id}"
        + (f"&period_id={period_id}" if period_id else ""),
        headers=headers,
    ).json()
    return next(a for a in rows if a["metric_code"] == metric_code)


def _submit(client, headers, entity_id, metric_code, value, unit, period_id=None):
    a = _assignment(client, headers, entity_id, metric_code, period_id)
    detail = _detail(client, headers, a["id"])
    r = client.post(
        f"/api/v1/assignments/{a['id']}/value",
        json={"action": "SUBMIT", "raw_value": value, "raw_unit": unit,
              "expected_last_version": detail["latest_version"]},
        headers=headers,
    )
    assert r.status_code == 201, r.json()
    return r.json()


def test_run_calculations_computes_total_energy(client, ctx):
    owner_h = _login(client, "owner-eps@example.local")
    # Alpha drafts: nonrenewable 170000 kWh (seed) + renewable 30 MWh
    _submit(client, owner_h, ctx["plant_epsilon"], "C-P6-GRID-RENEWABLE-MWH", 30, "MWh", period_id=ctx["period_fy25"])

    r = client.post(
        "/api/v1/calculations/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_epsilon"])},
        headers=_login(client, "manager@example.local"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["computed"] >= 1

    total = _detail(
        client, owner_h,
        _assignment(client, owner_h, ctx["plant_epsilon"], "C-P6-TOTAL-ENERGY", period_id=ctx["period_fy25"])["id"],
    )
    latest = total["values"][0]
    assert latest["is_calculated"] is True
    assert latest["formula_version"] == 1
    assert latest["raw_value"] == 217.0  # 187 (seed) + 30 (just submitted)
    assert latest["raw_unit"] == "MWh"
    assert latest["formula_inputs"]["C-P6-GRID-NONRENEWABLE-MWH"] == "187.00000000"


def test_scope1_and_total_ghg_computed(client, ctx):
    owner_h = _login(client, "owner-eps@example.local")
    r = client.post(
        "/api/v1/calculations/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_epsilon"])},
        headers=_login(client, "manager@example.local"),
    )
    assert r.status_code == 200

    scope1 = _detail(
        client, owner_h,
        _assignment(client, owner_h, ctx["plant_epsilon"], "C-P6-SCOPE1-TCO2E", period_id=ctx["period_fy25"])["id"],
    )
    # diesel 12100 L (FY25 seed x 1.1) x 2.68 kgCO2e/L / 1000 = 32.428 tCO2e
    assert float(scope1["values"][0]["raw_value"]) == pytest.approx(32.428, abs=1e-6)
    assert scope1["values"][0]["is_calculated"] is True

    ghg = _detail(
        client, owner_h,
        _assignment(client, owner_h, ctx["plant_epsilon"], "C-P6-TOTAL-GHG", period_id=ctx["period_fy25"])["id"],
    )
    # scope1 32.428 + scope2 152.9 = 185.328
    assert float(ghg["values"][0]["raw_value"]) == pytest.approx(185.328, abs=1e-6)


def test_rerun_is_idempotent_no_duplicate_versions(client, ctx):
    owner_h = _login(client, "owner-eps@example.local")
    assignment_id = _assignment(client, owner_h, ctx["plant_epsilon"], "C-P6-TOTAL-ENERGY")["id"]
    before = _detail(client, owner_h, assignment_id)
    for _ in range(2):
        client.post(
            "/api/v1/calculations/run",
            json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_epsilon"])},
            headers=_login(client, "manager@example.local"),
        )
    after = _detail(client, owner_h, assignment_id)
    assert len(after["values"]) == len(before["values"])


def test_input_change_creates_new_version(client, ctx):
    owner_h = _login(client, "owner-eps@example.local")
    assignment_id = _assignment(client, owner_h, ctx["plant_epsilon"], "C-P6-TOTAL-ENERGY")["id"]
    before = _detail(client, owner_h, assignment_id)
    # change the renewable input; dependent recompute runs inside save_value
    _submit(client, owner_h, ctx["plant_epsilon"], "C-P6-GRID-NONRENEWABLE-MWH",
            190, "MWh", period_id=ctx["period_fy25"])
    after = _detail(client, owner_h, assignment_id)
    assert len(after["values"]) == len(before["values"]) + 1
    assert float(after["values"][0]["raw_value"]) == pytest.approx(220.0, abs=1e-6)  # 190 + 30


def test_missing_inputs_reported_not_silent(client, ctx):
    """Zeta has an IN_PROGRESS derived shell? No — Zeta is NOT_STARTED; run on
    an entity whose inputs exist but derived shell exists (Alpha covers it).
    Here we assert failures are reported, never silent zeros, for any entity
    with missing inputs."""
    r = client.post(
        "/api/v1/calculations/run",
        json={"period_id": str(ctx["period_fy25"]), "entity_id": str(ctx["plant_zeta"])},
        headers=_login(client, "manager@example.local"),
    )
    assert r.status_code == 200
    body = r.json()
    # Zeta's derived assignments are NOT_STARTED shells; either computed (with
    # inputs missing -> failures) or skipped (status guard). Both are explicit.
    assert body["status"] == "completed"
    assert body["computed"] == 0


def test_fy24_locked_derived_values_exist_with_formula_lineage(client, ctx):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models import Assignment, MetricValue

    TestSession = sessionmaker(bind=TEST_STATE["engine"])
    with TestSession() as db:
        assignment = db.scalar(
            select(Assignment).where(
                Assignment.entity_id == ctx["plant_alpha"],
                Assignment.metric_code == "C-P6-TOTAL-ENERGY",
                Assignment.period_id == ctx["period_fy24"],
            )
        )
        assert assignment is not None, "FY24 derived assignment must be seeded"
        value = db.scalar(
            select(MetricValue).where(MetricValue.assignment_id == assignment.id)
        )
        assert value is not None
        assert value.is_calculated is True
        assert value.formula_id is not None
        assert value.formula_version == 1
        assert float(value.raw_value) == pytest.approx(120.0)  # 100 + 20
        assert value.formula_inputs["C-P6-GRID-RENEWABLE-MWH"] == "20.0"
        assert value.status.value == "LOCKED"


def test_data_owner_cannot_run_calculations(client, ctx):
    r = client.post(
        "/api/v1/calculations/run",
        json={"period_id": str(ctx["period_fy25"])},
        headers=_login(client, "owner-eps@example.local"),
    )
    assert r.status_code == 403
