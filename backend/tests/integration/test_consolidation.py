"""Consolidation golden tests (spec §13, §38 — HARD MERGE GATE).

The critical invariant: group ratios are ALWAYS
    sum(numerator) / sum(denominator)
never average(child percentages).
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

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

    from app.models import Entity, FrameworkVersion, ReportingPeriod

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)
        period = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2025-26"))
        yield {
            "db_maker": sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False),
            "period_id": period.id,
            "fv_id": period.framework_version_id,
        }


def _login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _approved_value(db, entity_id, period_id, fv_id, code, value, unit=None):
    """Insert an assignment + APPROVED MetricValue (reuses an existing
    assignment and appends a new approved version when one already exists)."""
    from decimal import Decimal

    from app.models import AppUser, Assignment, MetricValue
    from app.models.enums import AssignmentStatus, MetricValueStatus

    owner = db.scalar(select(AppUser).where(AppUser.email == "manager@example.local"))
    assignment = db.scalar(
        select(Assignment).where(
            Assignment.metric_code == code,
            Assignment.entity_id == entity_id,
            Assignment.period_id == period_id,
        )
    )
    if assignment is None:
        assignment = Assignment(
            metric_code=code, framework_version_id=fv_id, entity_id=entity_id,
            period_id=period_id, owner_user_id=owner.id,
            status=AssignmentStatus.APPROVED, created_by=owner.id,
        )
        db.add(assignment)
        db.flush()
        version = 1
    else:
        assignment.status = AssignmentStatus.APPROVED
        last = db.scalar(
            select(MetricValue.version)
            .where(MetricValue.assignment_id == assignment.id)
            .order_by(MetricValue.version.desc())
            .limit(1)
        )
        version = (last or 0) + 1
    db.add(MetricValue(
        assignment_id=assignment.id, version=version,
        raw_value=Decimal(str(value)), raw_unit=unit,
        normalized_value=Decimal(str(value)), normalized_unit=unit,
        status=MetricValueStatus.APPROVED, created_by=owner.id,
        submitted_by=owner.id,
    ))
    db.flush()
    return assignment.id


def _entity(db, name, entity_type, parent_id=None):
    from app.models import Entity
    from app.models.enums import EntityType

    entity = Entity(
        name=name, entity_type=entity_type, parent_id=parent_id,
        effective_from=date(2025, 4, 1),
    )
    db.add(entity)
    db.flush()
    return entity


def test_golden_ratio_recalculation_4_percent_not_6_665(client, ctx):
    """Plant A: 100/1000 = 10%. Plant B: 300/9000 = 3.33%.
    Group: 400/10000 = 4% — and explicitly NOT the 6.665% naive average."""
    from sqlalchemy import select

    from app.models import ConsolidationTrace, Entity

    with ctx["db_maker"]() as db:
        sub = _entity(db, f"Golden Sub {uuid.uuid4().hex[:6]}", "SUBSIDIARY")
        plant_a = _entity(db, f"Plant A {uuid.uuid4().hex[:6]}", "PLANT", sub.id)
        plant_b = _entity(db, f"Plant B {uuid.uuid4().hex[:6]}", "PLANT", sub.id)
        # waste-recycled percent: Plant A 100/1000 = 10%, Plant B 300/9000 = 3.33%
        _approved_value(db, plant_a.id, ctx["period_id"], ctx["fv_id"], "C-P6-WASTE-RECYCLED", 100)
        _approved_value(db, plant_a.id, ctx["period_id"], ctx["fv_id"], "C-P6-WASTE-GENERATED", 1000)
        _approved_value(db, plant_b.id, ctx["period_id"], ctx["fv_id"], "C-P6-WASTE-RECYCLED", 300)
        _approved_value(db, plant_b.id, ctx["period_id"], ctx["fv_id"], "C-P6-WASTE-GENERATED", 9000)
        db.commit()

        from app.consolidation import service

        trace = service.consolidate(db, sub.id, "C-P6-WASTE-RECYCLED-PCT", ctx["period_id"])
        db.commit()
        result = float(trace.computed_value)
        assert result == pytest.approx(4.0, abs=1e-9), \
            "group ratio must be sum(num)/sum(den) scaled to percent"
        # the naive average of child percentages would be 6.665 — must NOT match
        assert result != pytest.approx(6.665, abs=1e-2)

        # intensity metrics keep their unit scale: tCO2e per INR crore
        _approved_value(db, plant_a.id, ctx["period_id"], ctx["fv_id"], "C-P6-TOTAL-GHG", 100)
        _approved_value(db, plant_a.id, ctx["period_id"], ctx["fv_id"], "A-REVENUE", 1000)
        _approved_value(db, plant_b.id, ctx["period_id"], ctx["fv_id"], "C-P6-TOTAL-GHG", 300)
        _approved_value(db, plant_b.id, ctx["period_id"], ctx["fv_id"], "A-REVENUE", 9000)
        db.commit()
        intensity = service.consolidate(db, sub.id, "C-P6-GHG-INTENSITY", ctx["period_id"])
        db.commit()
        assert float(intensity.computed_value) == pytest.approx(0.04, abs=1e-9)  # 400/10000

        trace_total = service.consolidate(db, sub.id, "C-P6-TOTAL-GHG", ctx["period_id"])
        db.commit()
        assert float(trace_total.computed_value) == 400.0
        assert trace_total.aggregation_semantics == "SUM"


def test_sum_multi_level_hierarchy(client, ctx):
    """Plant -> BU -> Subsidiary -> Group: energy sums all the way up."""
    from app.consolidation import service

    with ctx["db_maker"]() as db:
        group = _entity(db, f"G {uuid.uuid4().hex[:6]}", "GROUP")
        sub = _entity(db, f"S {uuid.uuid4().hex[:6]}", "SUBSIDIARY", group.id)
        bu1 = _entity(db, f"BU {uuid.uuid4().hex[:6]}", "BUSINESS_UNIT", sub.id)
        bu2 = _entity(db, f"BU {uuid.uuid4().hex[:6]}", "BUSINESS_UNIT", sub.id)
        for bu, values in ((bu1, [10.0, 20.0]), (bu2, [30.0, 40.0])):
            for v in values:
                plant = _entity(db, f"P {uuid.uuid4().hex[:6]}", "PLANT", bu.id)
                _approved_value(db, plant.id, ctx["period_id"], ctx["fv_id"],
                                "C-P6-TOTAL-ENERGY", v, "MWh")
        db.commit()

        for entity_id, expected in ((bu1.id, 30.0), (sub.id, 100.0), (group.id, 100.0)):
            trace = service.consolidate(db, entity_id, "C-P6-TOTAL-ENERGY", ctx["period_id"])
            db.commit()
            assert float(trace.computed_value) == pytest.approx(expected, abs=1e-9)


def test_zero_denominator_raises_explicitly(client, ctx):
    from app.consolidation import service

    with ctx["db_maker"]() as db:
        sub = _entity(db, f"ZeroDen {uuid.uuid4().hex[:6]}", "SUBSIDIARY")
        plant = _entity(db, f"P {uuid.uuid4().hex[:6]}", "PLANT", sub.id)
        _approved_value(db, plant.id, ctx["period_id"], ctx["fv_id"], "C-P6-TOTAL-GHG", 100)
        # revenue deliberately absent -> denominator missing; and with 0 revenue
        _approved_value(db, plant.id, ctx["period_id"], ctx["fv_id"], "A-REVENUE", 0)
        db.commit()

        with pytest.raises(service.ConsolidationError, match="[Zz]ero denominator"):
            service.consolidate(db, sub.id, "C-P6-GHG-INTENSITY", ctx["period_id"])


def test_child_change_marks_parent_stale(client, ctx):
    from sqlalchemy import select

    from app.consolidation import service
    from app.models import ConsolidationTrace

    with ctx["db_maker"]() as db:
        sub = _entity(db, f"Stale {uuid.uuid4().hex[:6]}", "SUBSIDIARY")
        plant = _entity(db, f"P {uuid.uuid4().hex[:6]}", "PLANT", sub.id)
        _approved_value(db, plant.id, ctx["period_id"], ctx["fv_id"], "C-P6-TOTAL-GHG", 100)
        db.commit()

        trace = service.consolidate(db, sub.id, "C-P6-TOTAL-GHG", ctx["period_id"])
        db.commit()
        assert trace.is_stale is False

        # new approved child value arrives after consolidation
        _approved_value(db, plant.id, ctx["period_id"], ctx["fv_id"], "C-P6-TOTAL-GHG", 200)
        marked = service.mark_stale_upstream(db, plant.id, "C-P6-TOTAL-GHG", ctx["period_id"])
        db.commit()
        assert marked >= 1
        db.refresh(trace)
        assert trace.is_stale is True
        assert "recomputation" in trace.stale_reason.lower()

        # recompute brings it current again (latest approved version = 200)
        service.consolidate(db, sub.id, "C-P6-TOTAL-GHG", ctx["period_id"])
        db.commit()
        db.refresh(trace)
        assert trace.is_stale is False
        assert float(trace.computed_value) == 200.0


def test_direct_value_semantics(client, ctx):
    from app.consolidation import service

    with ctx["db_maker"]() as db:
        sub = _entity(db, f"DV {uuid.uuid4().hex[:6]}", "SUBSIDIARY")
        # a subsidiary-level value with no children consolidates as its own
        # approved value (leaf path) — the quantitative DIRECT case
        _approved_value(db, sub.id, ctx["period_id"], ctx["fv_id"], "C-P6-ENV-FINES", 2.5)
        db.commit()
        trace = service.consolidate(db, sub.id, "C-P6-ENV-FINES", ctx["period_id"])
        db.commit()
        assert float(trace.computed_value) == pytest.approx(2.5, abs=1e-9)
        assert trace.contributing_value_ids, "leaf contribution recorded"


def test_incomplete_consolidation_reports_missing_children(client, ctx):
    """One approved child + one unapproved child -> group value reflects only
    what is approved; the trace records fewer contributors (incomplete input)."""
    from app.consolidation import service

    with ctx["db_maker"]() as db:
        sub = _entity(db, f"Inc {uuid.uuid4().hex[:6]}", "SUBSIDIARY")
        p1 = _entity(db, f"P {uuid.uuid4().hex[:6]}", "PLANT", sub.id)
        p2 = _entity(db, f"P {uuid.uuid4().hex[:6]}", "PLANT", sub.id)
        _approved_value(db, p1.id, ctx["period_id"], ctx["fv_id"], "C-P6-TOTAL-GHG", 100)
        # p2 has NO approved value (only an unapproved one that must be ignored)
        _approved_value(db, p2.id, ctx["period_id"], ctx["fv_id"], "A-REVENUE", 500)
        from app.models import Assignment, MetricValue
        from app.models.enums import AssignmentStatus, MetricValueStatus

        from app.models import AppUser

        owner = db.scalar(select(AppUser).where(AppUser.email == "manager@example.local"))
        unapproved = Assignment(
            metric_code="C-P6-TOTAL-GHG", framework_version_id=ctx["fv_id"],
            entity_id=p2.id, period_id=ctx["period_id"], owner_user_id=owner.id,
            status=AssignmentStatus.IN_PROGRESS, created_by=owner.id,
        )
        db.add(unapproved)
        db.flush()
        db.add(MetricValue(
            assignment_id=unapproved.id, version=1, raw_value=Decimal("999"),
            normalized_value=Decimal("999"), status=MetricValueStatus.IN_PROGRESS,
            created_by=owner.id,
        ))
        db.commit()

        trace = service.consolidate(db, sub.id, "C-P6-TOTAL-GHG", ctx["period_id"])
        db.commit()
        assert float(trace.computed_value) == 100.0, "unapproved values must not consolidate"
        assert len(trace.contributing_value_ids) == 1


def test_consolidation_api_and_scope(client, ctx):
    """API: recompute (manager-only) then read a trace; owner of a foreign
    entity cannot read another entity's trace."""
    manager_h = _login(client, "manager@example.local")
    r = client.post(
        "/api/v1/consolidation/recompute",
        json={"period_id": str(ctx["period_id"]), "metric_code": "C-P6-TOTAL-ENERGY"},
        headers=manager_h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["consolidated"] > 0

    # FY2024-25 is fully locked: group-level energy must be complete
    from sqlalchemy import select

    from app.models import Entity, ReportingPeriod

    with ctx["db_maker"]() as db:
        group = db.scalar(select(Entity).where(Entity.name == "MEIL Group"))
        fy24 = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == "FY2024-25"))
        fy24_id = fy24.id
        group_id = group.id

    r = client.post(
        "/api/v1/consolidation/recompute",
        json={"period_id": str(fy24_id), "metric_code": "C-P6-TOTAL-ENERGY"},
        headers=manager_h,
    )
    assert r.status_code == 200

    owner_h = _login(client, "owner-alpha@example.local")
    read = client.get(
        f"/api/v1/consolidation/{group_id}/C-P6-TOTAL-ENERGY/{fy24_id}", headers=owner_h
    )
    assert read.status_code == 403, "Plant Alpha owner must not read Group-level consolidation"

    read_manager = client.get(
        f"/api/v1/consolidation/{group_id}/C-P6-TOTAL-ENERGY/{fy24_id}", headers=manager_h
    )
    assert read_manager.status_code == 200
    trace = read_manager.json()
    assert trace["is_stale"] is False
    assert trace["computed_value"] > 0
    assert trace["contributing_value_count"] >= 8  # all eight plants contributed


def test_audit_event_written_for_consolidation(client, ctx):
    from sqlalchemy import text

    manager_h = _login(client, "manager@example.local")
    client.post(
        "/api/v1/consolidation/recompute",
        json={"period_id": str(ctx["period_id"]), "metric_code": "C-P6-TOTAL-GHG"},
        headers=manager_h,
    )
    with TEST_STATE["engine"].connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM audit_event WHERE object_type='consolidation_trace'")
        ).scalar()
    assert count > 0
