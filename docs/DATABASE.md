# Database

PostgreSQL 16 · UUID primary keys · native enums · Alembic migrations ·
21 domain tables (see `backend/app/models/`):

```
app_user ──< user_entity_scope >── entity (recursive adjacency list,
                                    traversed via recursive CTE)
framework_version ──< metric_definition (>── formula_definition ──< formula_version)
        │                    │
        │                    └──< metric_lineage >── framework_version (cross-version)
        └──< reporting_period ──< assignment ──< metric_value (immutable versions)
                                                │
                validation_rule ──< validation_exception
                                                │
                                        evidence (MinIO bytes, SHA-256)

consolidation_trace (entity, metric, period) — read model with contributing
value ids + staleness · report_snapshot (immutable JSONB + checksum) ──<
generated_report · audit_event (append-only, mutation blocked by trigger) ·
notification · ai_suggestion · bulk_import_job
```

Key constraints: unique metric_code per framework version; Section C metrics
require a principle; RATIO_RECALCULATION requires numerator+denominator;
unique (assignment, version); audit_event immutability trigger; effective
date ordering on entities and periods.
