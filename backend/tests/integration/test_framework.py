"""Framework-engine integration tests: catalogue, metadata validation, API."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import CURRENT_FV, DEMO_PASSWORD, PREVIOUS_FV, seed

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
def seeded(migrated_engine):
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def version_ids(client, seeded):
    versions = client.get("/api/v1/framework/versions", headers=_login(client, "admin@example.local")).json()
    return {v["version_code"]: v["id"] for v in versions}


def test_two_framework_versions_seeded(client, seeded, version_ids):
    assert CURRENT_FV in version_ids and PREVIOUS_FV in version_ids


def test_current_catalogue_size_and_sections(client, seeded, version_ids):
    metrics = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    assert 40 <= len(metrics) <= 60
    sections = {m["section"] for m in metrics}
    assert sections == {"A", "B", "C"}
    principles = {m["principle"] for m in metrics if m["section"] == "C"}
    assert principles == {f"P{i}" for i in range(1, 10)}


def test_brsr_core_indicator_count(client, seeded, version_ids):
    metrics = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics?brsr_core=true",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    assert len(metrics) >= 15
    assert all(m["brsr_core"] for m in metrics)


def test_every_section_c_metric_has_principle(client, seeded, version_ids):
    metrics = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    for m in metrics:
        if m["section"] == "C":
            assert m["principle"] in {f"P{i}" for i in range(1, 10)}


def test_ratio_metrics_have_numerator_and_denominator(client, seeded, version_ids):
    metrics = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    ratios = [m for m in metrics if m["aggregation_semantics"] == "RATIO_RECALCULATION"]
    assert len(ratios) >= 5
    for m in ratios:
        assert m["ratio_numerator_code"] and m["ratio_denominator_code"]


def test_intensity_metrics_are_ratio_not_average(client, seeded, version_ids):
    metrics = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    by_code = {m["metric_code"]: m for m in metrics}
    for code in ("C-P6-GHG-INTENSITY", "C-P6-ENERGY-INTENSITY", "C-P6-WATER-INTENSITY"):
        assert by_code[code]["aggregation_semantics"] == "RATIO_RECALCULATION"


def test_formulas_and_rules_seeded(client, seeded, version_ids):
    formulas = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/formulas",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    assert {f["code"] for f in formulas} >= {"F-TOTAL-ENERGY", "F-SCOPE1", "F-TOTAL-GHG"}
    rules = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/rules",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    classes = {r["rule_class"] for r in rules}
    assert classes == {
        "REQUIRED_FIELD", "RANGE_VALIDATION", "UNIT_VALIDATION", "TYPE_VALIDATION",
        "DUPLICATE_DETECTION", "CROSS_FIELD_RECONCILIATION", "CROSS_SECTION_RECONCILIATION",
        "YOY_VARIANCE", "EVIDENCE_COMPLETENESS", "LOGICAL_CONSISTENCY",
    }


def test_admin_adds_metric_and_it_appears_dynamically(client, seeded, version_ids):
    """HARD ACCEPTANCE TEST: a new metric inserted via metadata appears in the
    catalogue without any code change."""
    headers = _login(client, "admin@example.local")
    unique = uuid.uuid4().hex[:6]
    r = client.post(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        json={
            "metric_code": f"C-P6-DYNAMIC-{unique}",
            "section": "C",
            "principle": "P6",
            "label": f"Dynamically added metric {unique}",
            "data_type": "numeric",
            "unit_family": "energy",
            "canonical_unit": "MWh",
            "required": True,
            "aggregation_semantics": "SUM",
            "brsr_core": False,
        },
        headers=headers,
    )
    assert r.status_code == 201
    metrics = client.get(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics?section=C&principle=P6",
        headers=_login(client, "owner-alpha@example.local"),
    ).json()
    assert any(m["metric_code"] == f"C-P6-DYNAMIC-{unique}" for m in metrics)


def test_non_admin_cannot_add_metric(client, seeded, version_ids):
    r = client.post(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        json={
            "metric_code": "C-P6-HACK", "section": "C", "principle": "P6",
            "label": "Hack", "data_type": "numeric", "aggregation_semantics": "SUM",
        },
        headers=_login(client, "manager@example.local"),
    )
    assert r.status_code == 403


def test_ratio_metric_without_numerator_rejected(client, seeded, version_ids):
    r = client.post(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        json={
            "metric_code": "C-P6-BAD-RATIO", "section": "C", "principle": "P6",
            "label": "Bad ratio", "data_type": "numeric",
            "aggregation_semantics": "RATIO_RECALCULATION",
        },
        headers=_login(client, "admin@example.local"),
    )
    assert r.status_code == 422
    assert "numerator" in r.json()["detail"].lower()


def test_section_c_without_principle_rejected_via_api(client, seeded, version_ids):
    r = client.post(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        json={
            "metric_code": "C-BAD-NO-PRINCIPLE", "section": "C",
            "label": "No principle", "data_type": "numeric",
            "aggregation_semantics": "SUM",
        },
        headers=_login(client, "admin@example.local"),
    )
    assert r.status_code == 422
    assert "principle" in r.json()["detail"].lower()


def test_duplicate_metric_code_rejected_via_api(client, seeded, version_ids):
    r = client.post(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        json={
            "metric_code": "A-REVENUE", "section": "A", "label": "Duplicate revenue",
            "data_type": "numeric", "aggregation_semantics": "SUM",
        },
        headers=_login(client, "admin@example.local"),
    )
    assert r.status_code == 422


def test_ratio_reference_to_missing_code_rejected(client, seeded, version_ids):
    r = client.post(
        f"/api/v1/framework/versions/{version_ids[CURRENT_FV]}/metrics",
        json={
            "metric_code": "C-P9-RATIO-BADREF", "section": "C", "principle": "P9",
            "label": "Bad ref", "data_type": "numeric",
            "aggregation_semantics": "RATIO_RECALCULATION",
            "ratio_numerator_code": "NO-SUCH-CODE",
            "ratio_denominator_code": "C-P9-COMPLAINTS",
        },
        headers=_login(client, "admin@example.local"),
    )
    assert r.status_code == 422
    assert "NO-SUCH-CODE" in r.json()["detail"]


def test_previous_version_has_lineage_mappings(client, seeded, version_ids):
    from sqlalchemy import text

    with TEST_STATE["engine"].connect() as conn:
        direct = conn.execute(
            text(
                "SELECT count(*) FROM metric_lineage WHERE mapping_type='DIRECT' "
                "AND from_framework_version_id = "
                "(SELECT id FROM framework_version WHERE version_code = :p)"
            ),
            {"p": PREVIOUS_FV},
        ).scalar()
        renamed = conn.execute(
            text("SELECT count(*) FROM metric_lineage WHERE mapping_type='REDEFINED'")
        ).scalar()
    assert direct >= 20
    assert renamed >= 1
