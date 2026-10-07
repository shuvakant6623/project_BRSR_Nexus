# Architecture

Metadata-driven modular monolith + async worker layer (FastAPI + PostgreSQL + Redis/RustFS +
Celery + Next.js 15).

```
                      BROWSER (Next.js App Router)
                                │ HTTPS/JSON
                                ▼
                   FASTAPI MODULAR API  ─── /healthz  /readyz
        ┌──────────┬─────────┼──────────┬─────────────┐
        ▼          ▼         ▼          ▼             ▼
      AUTH      FRAMEWORK  COLLECTION  EVIDENCE    REPORTING
      (JWT,      (versions, (assign-    (RustFS,    (lock → snapshot
      RBAC,      metrics,   ments,      SHA-256,    → async PDF)
      scopes)    rules,     MetricValue signed
                 formulas)  versioning) URLs)
        │          │         │
        │          ▼         ▼
        │     VALIDATION ── CALCULATION ──► CONSOLIDATION
        │     (10 rule      (safe Decimal   (Σnum/Σden per
        │     classes +     evaluator,      hierarchy level,
        │     statistical   no eval)        traces, stale
        │     IQR/z-score)                  marking)
        │
        ▼
      AUDIT (append-only, DB trigger) ──► LINEAGE (read model)
        │
        ▼
      NOTIFICATIONS ◄── Celery Beat (hourly reminder scan)
        │
        ▼
      DASHBOARD / TRENDS (live aggregation, zero hard-coded numbers)

  ASYNC: FastAPI → Redis → Celery worker (report PDF, bulk import,
  reminder scans) + Celery beat.
```

## Modules (backend/app/*)
Each domain module is self-contained (`service.py` for business logic, `router.py` for HTTP):
auth, entities, framework, collection, normalization, validation (+ statistics), calculation,
consolidation, evidence, audit, lineage, reporting, dashboard, trends, imports, notifications,
ai, workflow. `workers/` contains ONLY thin Celery task wrappers — all logic lives in domain
services and is testable without Celery. `audit` is a shared dependency and never imports
business modules.

## Core invariants
1. Every MetricValue is immutable-versioned; corrections create new versions.
2. Every business write emits an audit event in the SAME transaction (audit insert failure
   rolls back the write).
3. RBAC and entity-scope are enforced server-side on every endpoint.
4. Ratio/intensity consolidation is always Σnumerator/Σdenominator — never averaged.
5. AI suggestions are drafts only; acceptance creates an owner-authored IN_PROGRESS value.
6. Reports render exclusively from checksummed immutable snapshots of LOCKED periods.
7. Formulas, validation rules and the metric catalogue are database metadata — regulatory
   change is a data change, not a code change.
