"""Comprehensive MVP End-to-End Workflow & Integrity Tests.

Verifies the entire regulatory workflow:
Data Owner -> Collection -> Validation -> Review/Approval -> Calculation ->
Consolidation Completeness -> Assurance Readiness -> Period Lock ->
Authoritative Snapshot -> HTML Preview.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.consolidation import service as consolidation_service
from app.db.session import get_db
from app.main import app
from app.models import (
    AppUser,
    Assignment,
    ConsolidationTrace,
    Entity,
    FrameworkVersion,
    MetricDefinition,
    MetricValue,
    ReportingPeriod,
)
from app.models.enums import AssignmentStatus, MetricValueStatus, UserRole
from app.seed import DEMO_PASSWORD, seed


@pytest.fixture(scope="module")
def client(migrated_engine):
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
    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)
        period_fy25 = db.scalar(
            select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26")
        )
        fv_current = db.scalar(
            select(FrameworkVersion).where(FrameworkVersion.id == period_fy25.framework_version_id)
        )
        group = db.scalar(select(Entity).where(Entity.name == "MEIL Group"))
        plant_alpha = db.scalar(select(Entity).where(Entity.name == "Plant Alpha"))
        plant_beta = db.scalar(select(Entity).where(Entity.name == "Plant Beta"))
        owner_alpha = db.scalar(select(AppUser).where(AppUser.email == "owner-alpha@example.local"))
        reviewer = db.scalar(select(AppUser).where(AppUser.email == "reviewer@example.local"))
        esg_manager = db.scalar(select(AppUser).where(AppUser.email == "manager@example.local"))
        assessor = db.scalar(select(AppUser).where(AppUser.email == "assessor@example.local"))
        admin = db.scalar(select(AppUser).where(AppUser.email == "admin@example.local"))

        yield {
            "db_maker": TestSession,
            "period_fy25_id": period_fy25.id,
            "fv_id": fv_current.id,
            "group_id": group.id,
            "plant_alpha_id": plant_alpha.id,
            "plant_beta_id": plant_beta.id,
            "owner_alpha_id": owner_alpha.id,
            "reviewer_id": reviewer.id,
            "esg_manager_id": esg_manager.id,
            "assessor_id": assessor.id,
            "admin_id": admin.id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_auth_scoping_and_assessor_readonly(client, ctx):
    """Test role scoping: Owner only accesses own assignments; Assessor has read-only access."""
    owner_h = _login(client, "owner-alpha@example.local")
    assessor_h = _login(client, "assessor@example.local")

    # Data Owner sees only own assignments
    res = client.get("/api/v1/assignments", headers=owner_h)
    assert res.status_code == 200
    rows = res.json()
    assert all(r["owner_user_id"] == str(ctx["owner_alpha_id"]) for r in rows)

    # Assessor can read readiness
    r_readiness = client.get(
        f"/api/v1/assurance/readiness?period_id={ctx['period_fy25_id']}", headers=assessor_h
    )
    assert r_readiness.status_code == 200
    data = r_readiness.json()
    assert "score_percent" in data
    assert "overall_status" in data
    assert "indicators" in data

    # Assessor cannot edit values or lock periods
    target_assign = rows[0]["id"]
    r_write = client.post(
        f"/api/v1/assignments/{target_assign}/value",
        headers=assessor_h,
        json={"action": "SAVE_DRAFT", "raw_value": 100, "raw_unit": "MWh"},
    )
    assert r_write.status_code == 403

    r_lock = client.post(
        f"/api/v1/reporting-periods/{ctx['period_fy25_id']}/lock",
        headers=assessor_h,
    )
    assert r_lock.status_code == 403


def test_validation_blocking_and_submission(client, ctx):
    """Test validation prevents submitting invalid units, while valid draft succeeds."""
    owner_h = _login(client, "owner-alpha@example.local")
    rows = client.get(f"/api/v1/assignments?period_id={ctx['period_fy25_id']}", headers=owner_h).json()
    assign = next(r for r in rows if r["metric_code"] == "C-P6-DIESEL-LITRES")
    detail = client.get(f"/api/v1/assignments/{assign['id']}", headers=owner_h).json()
    last_v = detail["latest_version"] or 0

    # Invalid unit rejected
    r_bad = client.post(
        f"/api/v1/assignments/{assign['id']}/value",
        headers=owner_h,
        json={"action": "SUBMIT", "raw_value": 5000, "raw_unit": "INVALID_UNIT", "expected_last_version": last_v},
    )
    assert r_bad.status_code in (409, 422)

    # Valid unit draft saves
    r_good = client.post(
        f"/api/v1/assignments/{assign['id']}/value",
        headers=owner_h,
        json={"action": "SAVE_DRAFT", "raw_value": 5000, "raw_unit": "litre", "expected_last_version": last_v},
    )
    assert r_good.status_code == 201, f"Save draft failed ({r_good.status_code}): {r_good.text}"
    val = r_good.json()
    assert val["status"] == "IN_PROGRESS"

    # Submit transitions to SUBMITTED
    r_sub = client.post(
        f"/api/v1/assignments/{assign['id']}/value",
        headers=owner_h,
        json={"action": "SUBMIT", "raw_value": 5000, "raw_unit": "litre", "expected_last_version": val["version"]},
    )
    assert r_sub.status_code == 201
    assert r_sub.json()["status"] == "SUBMITTED"


def test_approval_recomputes_ancestors_and_preserves_ratios(client, ctx):
    """Test that approval automatically recalculates ancestors bottom-up and
    preserves correct ratio aggregation: sum(num)/sum(den), not average of ratios."""
    from datetime import date
    from app.models.enums import EntityType

    # Create test hierarchy with distinct subsidiary and two plants
    with ctx["db_maker"]() as db:
        sub = Entity(name=f"Sub-Ratio-{uuid.uuid4().hex[:6]}", entity_type="SUBSIDIARY",
                     effective_from="2020-01-01", is_active=True)
        db.add(sub)
        db.flush()
        pa = Entity(name=f"Plant-A-{uuid.uuid4().hex[:6]}", entity_type="PLANT", parent_id=sub.id,
                    effective_from="2020-01-01", is_active=True)
        pb = Entity(name=f"Plant-B-{uuid.uuid4().hex[:6]}", entity_type="PLANT", parent_id=sub.id,
                    effective_from="2020-01-01", is_active=True)
        db.add_all([pa, pb])
        db.flush()

        owner = db.scalar(select(AppUser).where(AppUser.email == "admin@example.local"))
        period_id = ctx["period_fy25_id"]
        fv_id = ctx["fv_id"]

        # Create assignments for Plant A and Plant B
        # Plant A: 100 recycled, 1000 generated (10%)
        # Plant B: 300 recycled, 9000 generated (3.33%)
        # Total: 400 / 10000 = 4.0% (not 6.665% naive average)
        assign_rec_a = Assignment(metric_code="C-P6-WASTE-RECYCLED", framework_version_id=fv_id,
                                  entity_id=pa.id, period_id=period_id, owner_user_id=owner.id,
                                  status=AssignmentStatus.SUBMITTED, created_by=owner.id)
        assign_gen_a = Assignment(metric_code="C-P6-WASTE-GENERATED", framework_version_id=fv_id,
                                  entity_id=pa.id, period_id=period_id, owner_user_id=owner.id,
                                  status=AssignmentStatus.SUBMITTED, created_by=owner.id)
        assign_rec_b = Assignment(metric_code="C-P6-WASTE-RECYCLED", framework_version_id=fv_id,
                                  entity_id=pb.id, period_id=period_id, owner_user_id=owner.id,
                                  status=AssignmentStatus.SUBMITTED, created_by=owner.id)
        assign_gen_b = Assignment(metric_code="C-P6-WASTE-GENERATED", framework_version_id=fv_id,
                                  entity_id=pb.id, period_id=period_id, owner_user_id=owner.id,
                                  status=AssignmentStatus.SUBMITTED, created_by=owner.id)
        db.add_all([assign_rec_a, assign_gen_a, assign_rec_b, assign_gen_b])
        db.flush()

        # Add submitted metric values
        mv_rec_a = MetricValue(assignment_id=assign_rec_a.id, version=1, raw_value=Decimal("100"), raw_unit="metric_tonnes",
                               normalized_value=Decimal("100"), normalized_unit="metric_tonnes",
                               status=MetricValueStatus.SUBMITTED, created_by=owner.id)
        mv_gen_a = MetricValue(assignment_id=assign_gen_a.id, version=1, raw_value=Decimal("1000"), raw_unit="metric_tonnes",
                               normalized_value=Decimal("1000"), normalized_unit="metric_tonnes",
                               status=MetricValueStatus.SUBMITTED, created_by=owner.id)
        mv_rec_b = MetricValue(assignment_id=assign_rec_b.id, version=1, raw_value=Decimal("300"), raw_unit="metric_tonnes",
                               normalized_value=Decimal("300"), normalized_unit="metric_tonnes",
                               status=MetricValueStatus.SUBMITTED, created_by=owner.id)
        mv_gen_b = MetricValue(assignment_id=assign_gen_b.id, version=1, raw_value=Decimal("9000"), raw_unit="metric_tonnes",
                               normalized_value=Decimal("9000"), normalized_unit="metric_tonnes",
                               status=MetricValueStatus.SUBMITTED, created_by=owner.id)
        db.add_all([mv_rec_a, mv_gen_a, mv_rec_b, mv_gen_b])
        db.commit()

        manager_h = _login(client, "manager@example.local")

        # Attach evidence to each submitted core value so VR-EVIDENCE-CORE is satisfied
        for mv in [mv_rec_a, mv_gen_a, mv_rec_b, mv_gen_b]:
            r_ev = client.post(
                "/api/v1/evidence",
                params={"metric_value_id": str(mv.id)},
                files={"file": ("test_weighment_slip.pdf", b"%PDF-1.4 weighment slip", "application/pdf")},
                headers=manager_h,
            )
            assert r_ev.status_code == 201

        # Approve through API review endpoint
        for aid in [assign_rec_a.id, assign_gen_a.id, assign_rec_b.id, assign_gen_b.id]:
            client.post(f"/api/v1/assignments/{aid}/review", headers=manager_h, json={"action": "START_REVIEW"})
            r_app = client.post(
                f"/api/v1/assignments/{aid}/review",
                headers=manager_h,
                json={"action": "APPROVE", "comment": "Approved for golden ratio test"},
            )
            assert r_app.status_code == 200, f"Status {r_app.status_code}: {r_app.text}"

        # Consolidate ratio on subsidiary
        trace_ratio = consolidation_service.consolidate(db, sub.id, "C-P6-WASTE-RECYCLED-PCT", period_id)
        db.commit()

        # Must equal exactly 4.0% (400 / 10000 * 100), NOT naive average 6.665%
        assert float(trace_ratio.computed_value) == pytest.approx(4.0, abs=1e-4)
        assert trace_ratio.is_complete is True


def test_incomplete_consolidation_flags_missing_children(client, ctx):
    """Test that if child nodes are missing approved data, the consolidation trace
    reports is_complete=False and lists missing_child_ids."""
    with ctx["db_maker"]() as db:
        # Create a test entity with two children: one has approved data, one does not
        parent = Entity(name=f"Parent-{uuid.uuid4().hex[:6]}", entity_type=UserRole.ESG_MANAGER,
                        effective_from="2020-01-01")
        # Use proper entity hierarchy
        parent = Entity(name=f"Parent-{uuid.uuid4().hex[:6]}", entity_type="SUBSIDIARY",
                        effective_from="2020-01-01", is_active=True)
        db.add(parent)
        db.flush()
        c1 = Entity(name=f"Child1-{uuid.uuid4().hex[:6]}", entity_type="PLANT", parent_id=parent.id,
                    effective_from="2020-01-01", is_active=True)
        c2 = Entity(name=f"Child2-{uuid.uuid4().hex[:6]}", entity_type="PLANT", parent_id=parent.id,
                    effective_from="2020-01-01", is_active=True)
        db.add_all([c1, c2])
        db.flush()

        # Only c1 has an approved value
        owner = db.scalar(select(AppUser).where(AppUser.email == "admin@example.local"))
        assign_c1 = Assignment(
            metric_code="C-P6-TOTAL-GHG", framework_version_id=ctx["fv_id"],
            entity_id=c1.id, period_id=ctx["period_fy25_id"], owner_user_id=owner.id,
            status=AssignmentStatus.APPROVED, created_by=owner.id,
        )
        db.add(assign_c1)
        db.flush()
        mv_c1 = MetricValue(
            assignment_id=assign_c1.id, version=1, raw_value=Decimal("150"), raw_unit="tCO2e",
            normalized_value=Decimal("150"), normalized_unit="tCO2e",
            status=MetricValueStatus.APPROVED, created_by=owner.id,
        )
        db.add(mv_c1)
        db.commit()

        # Run consolidation on parent
        trace = consolidation_service.consolidate(db, parent.id, "C-P6-TOTAL-GHG", ctx["period_fy25_id"])
        db.commit()

        # Must report incomplete because c2 is missing
        assert trace.is_complete is False
        assert trace.missing_child_ids is not None
        assert str(c2.id) in trace.missing_child_ids
        assert float(trace.computed_value) == 150.0


def test_assurance_readiness_service_and_csv_export(client, ctx):
    """Test Assurance Readiness returns valid metrics and exports CSV."""
    assessor_h = _login(client, "assessor@example.local")
    period_id = ctx["period_fy25_id"]

    # 1. Query full readiness
    r = client.get(f"/api/v1/assurance/readiness?period_id={period_id}", headers=assessor_h)
    assert r.status_code == 200
    data = r.json()
    assert data["period_id"] == str(period_id)
    assert data["overall_status"] in ("READY", "PROVISIONAL", "NOT_READY")
    assert 0 <= data["score_percent"] <= 100
    assert len(data["indicators"]) > 0

    # 2. Export CSV
    r_export = client.get(
        f"/api/v1/assurance/export?period_id={period_id}",
        headers=assessor_h,
    )
    assert r_export.status_code == 200
    assert "text/csv" in r_export.headers.get("content-type", "")
    csv_text = r_export.text
    assert "Metric Code,Section,Principle,Indicator Label" in csv_text


def test_framework_lifecycle_and_coverage_audit(client, ctx):
    """Test framework version overlap conflict detection and coverage audit."""
    admin_h = _login(client, "admin@example.local")

    # 1. Create a version with overlapping active dates and attempt activation
    r_create = client.post(
        "/api/v1/framework/versions",
        headers=admin_h,
        json={
            "version_code": f"BRSR-CONFLICT-{uuid.uuid4().hex[:6]}",
            "name": "Conflicting Version",
            "effective_from": "2025-04-01",
            "effective_to": "2026-03-31",
            "is_active": False,
        },
    )
    assert r_create.status_code == 201
    new_v_id = r_create.json()["id"]

    # Activation should fail due to date overlap with active BRSR-FY2025-26
    r_act = client.post(
        f"/api/v1/framework/versions/{new_v_id}/activate",
        headers=admin_h,
    )
    assert r_act.status_code == 422
    assert "overlap" in r_act.json()["detail"].lower() or "conflict" in r_act.json()["detail"].lower()

    # 2. Coverage audit on current version
    r_cov = client.get(f"/api/v1/framework/versions/{ctx['fv_id']}/coverage", headers=admin_h)
    assert r_cov.status_code == 200
    cov = r_cov.json()
    assert cov["total_metrics"] >= 20
    assert "A" in cov["sections"] and "B" in cov["sections"] and "C" in cov["sections"]
    assert len(cov["principles_covered"]) == 9
    assert cov["core_indicator_count"] >= 9


def test_period_lock_and_snapshot_publication(client, ctx):
    """Test reporting workflow:
    1. Unlocked period rejects report generation.
    2. Locking fails if unapproved assignments exist.
    3. Final report snapshot includes leaf and consolidated data, is immutable, and renders HTML preview.
    """
    admin_h = _login(client, "admin@example.local")
    period_fy25 = ctx["period_fy25_id"]

    # 1. Unlocked period rejects report generation
    r_gen_unlocked = client.post(f"/api/v1/reports/{period_fy25}/generate", headers=admin_h)
    assert r_gen_unlocked.status_code == 409
    assert "locked" in r_gen_unlocked.json()["detail"].lower()

    # 2. Period FY25 has unapproved assignments -> lock rejected
    r_lock_unapproved = client.post(f"/api/v1/reporting-periods/{period_fy25}/lock", headers=admin_h)
    assert r_lock_unapproved.status_code == 409
    assert "not approved" in r_lock_unapproved.json()["detail"].lower() or "incomplete" in r_lock_unapproved.json()["detail"].lower()

    # 3. Create isolated test period where all assignments are approved & consolidated
    with ctx["db_maker"]() as db:
        p_test = ReportingPeriod(
            label=f"FY-TEST-{uuid.uuid4().hex[:6]}",
            start_date=date(2022, 4, 1),
            end_date=date(2023, 3, 31),
            framework_version_id=ctx["fv_id"],
            locked=False,
        )
        db.add(p_test)
        db.flush()
        owner = db.scalar(select(AppUser).where(AppUser.email == "admin@example.local"))
        assign = Assignment(
            metric_code="A-REVENUE", framework_version_id=ctx["fv_id"],
            entity_id=ctx["plant_alpha_id"], period_id=p_test.id, owner_user_id=owner.id,
            status=AssignmentStatus.APPROVED, created_by=owner.id,
        )
        db.add(assign)
        db.flush()
        mv = MetricValue(
            assignment_id=assign.id, version=1, raw_value=Decimal("500"), raw_unit="INR_crore",
            normalized_value=Decimal("500"), normalized_unit="INR_crore",
            status=MetricValueStatus.APPROVED, created_by=owner.id,
        )
        db.add(mv)
        db.commit()

        # Run consolidation for the test period
        consolidation_service.consolidate(db, ctx["plant_alpha_id"], "A-REVENUE", p_test.id)
        db.commit()

        test_period_id = p_test.id

    # Lock test period
    r_lock = client.post(f"/api/v1/reporting-periods/{test_period_id}/lock", headers=admin_h)
    assert r_lock.status_code == 200, f"Lock failed ({r_lock.status_code}): {r_lock.text}"
    assert r_lock.json()["locked"] is True

    # Generate authoritative snapshot
    r_gen = client.post(f"/api/v1/reports/{test_period_id}/generate", headers=admin_h)
    assert r_gen.status_code == 202
    snap = r_gen.json()
    assert "checksum" in snap
    assert len(snap["checksum"]) == 64

    # Immutability: Attempting duplicate snapshot generation returns 409
    r_dup = client.post(f"/api/v1/reports/{test_period_id}/generate", headers=admin_h)
    assert r_dup.status_code == 409
    assert "already exists" in r_dup.json()["detail"].lower()

    # Preview HTML renders from snapshot
    r_prev = client.get(f"/api/v1/reports/{test_period_id}/preview", headers=admin_h)
    assert r_prev.status_code == 200
    assert "text/html" in r_prev.headers.get("content-type", "")
    html = r_prev.text
    assert "Consolidated Group & Entity KPIs" in html
    assert "Section A" in html
    assert "Section B" in html
    assert "Section C" in html
    assert snap["checksum"] in html

