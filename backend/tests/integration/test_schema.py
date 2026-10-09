"""Integration tests: schema, constraints and the audit immutability trigger."""
import uuid

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.models.enums import AggregationSemantics, MetricDataType
from app.models.framework import FrameworkVersion, MetricDefinition


def test_all_core_tables_exist(migrated_engine):
    expected = {
        "app_user", "user_entity_scope", "entity", "framework_version",
        "metric_definition", "validation_rule", "formula_definition",
        "formula_version", "reporting_period", "assignment", "metric_value",
        "validation_exception", "evidence", "consolidation_trace",
        "audit_event", "report_snapshot", "generated_report", "notification",
        "ai_suggestion", "bulk_import_job", "metric_lineage",
    }
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        ).scalars().all()
    missing = expected - set(rows)
    assert not missing, f"missing tables: {missing}"


def _make_metric(session, fv_id, code, section, principle=None, agg=AggregationSemantics.SUM):
    return {
        "framework_version_id": fv_id,
        "metric_code": code,
        "section": section,
        "principle": principle,
        "label": f"Label {code}",
        "data_type": MetricDataType.NUMERIC,
        "aggregation_semantics": agg,
    }


def test_duplicate_metric_code_rejected(db):
    fv = FrameworkVersion(version_code=f"v-{uuid.uuid4().hex[:8]}", name="FV")
    db.add(fv)
    db.flush()
    db.execute(
        insert(MetricDefinition).values(_make_metric(db, fv.id, "E1", "A", agg=AggregationSemantics.DIRECT_VALUE))
    )
    with pytest.raises(IntegrityError):
        db.execute(
            insert(MetricDefinition).values(_make_metric(db, fv.id, "E1", "A", agg=AggregationSemantics.DIRECT_VALUE))
        )


def test_section_c_without_principle_rejected(db):
    fv = FrameworkVersion(version_code=f"v-{uuid.uuid4().hex[:8]}", name="FV")
    db.add(fv)
    db.flush()
    with pytest.raises(IntegrityError):
        db.execute(insert(MetricDefinition).values(_make_metric(db, fv.id, "P1X", "C")))


def test_ratio_metric_requires_numerator_and_denominator(db):
    fv = FrameworkVersion(version_code=f"v-{uuid.uuid4().hex[:8]}", name="FV")
    db.add(fv)
    db.flush()
    with pytest.raises(IntegrityError):
        db.execute(
            insert(MetricDefinition).values(
                _make_metric(db, fv.id, "R1", "C", principle="P6", agg=AggregationSemantics.RATIO_RECALCULATION)
            )
        )


def test_audit_event_is_immutable(migrated_engine):
    with migrated_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_event (id, actor_label, action, object_type) "
                "VALUES (gen_random_uuid(), 'tester', 'CREATED', 'test') "
            )
        )
        conn.commit()
        audit_id = conn.execute(
            text("SELECT id FROM audit_event WHERE actor_label='tester' ORDER BY created_at DESC LIMIT 1")
        ).scalar()
        with pytest.raises(ProgrammingError, match="immutable"):
            conn.execute(
                text("UPDATE audit_event SET actor_label='tampered' WHERE id=:i"), {"i": audit_id}
            ).all()
        conn.rollback()
        # deletion is also blocked by the trigger; disable (table-owner
        # permission), clean up, and re-enable
        conn.execute(text("ALTER TABLE audit_event DISABLE TRIGGER audit_event_immutable"))
        conn.execute(text("DELETE FROM audit_event WHERE actor_label='tester'"))
        conn.commit()
        conn.execute(text("ALTER TABLE audit_event ENABLE TRIGGER audit_event_immutable"))
        conn.commit()


# --- regression test: no duplicate route registration ------------------------

def test_reporting_periods_route_registered_once():
    """Regression: main.py used to include the reporting router twice, so
    /api/v1/reporting-periods was registered twice (latent middleware/audit
    double-execution hazard)."""
    from fastapi.routing import APIRoute

    from app.main import app

    paths: list[str] = []

    def _collect(router) -> None:
        for r in router.routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:  # _IncludedRouter wrapper (newer FastAPI)
                _collect(inner)
            elif isinstance(r, APIRoute):
                paths.append(r.path)

    _collect(app)
    assert paths.count("/api/v1/reporting-periods") == 1
