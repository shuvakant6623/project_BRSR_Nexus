# BRSR Reporting Portal

A metadata-driven BRSR (Business Responsibility and Sustainability Reporting) data-management and
reporting platform, built as a modular monolith with an async worker layer.

**Status: Phases 1–7 complete.** Docker stack, full database schema, auth/RBAC, entity
hierarchy, metadata-driven BRSR framework (57 metrics, 2 versions), data collection with
immutable value versioning, and unit normalization are implemented and tested (67 tests).
Remaining phases: validation engine, calculation, consolidation, evidence, lineage, assurance,
reporting, dashboard, trends, bulk import, notifications, AI/OCR (see `docs/`).

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Services:

| Service    | URL                    |
| ---------- | ---------------------- |
| Frontend   | http://localhost:3000  |
| Backend API| http://localhost:8000  |
| API docs   | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

## Verification (Phase 1)

```bash
curl http://localhost:8000/healthz   # -> {"status":"ok"}
curl http://localhost:8000/readyz    # -> {"status":"ready","dependencies":{...}}
```

`/readyz` performs live checks against PostgreSQL, Redis and MinIO and returns 503 when any
dependency is down.

## Demo credentials

All demo accounts use the password `Demo@12345` (development/demo only).

| Email | Role |
| ----- | ---- |
| admin@example.local | ADMIN |
| manager@example.local | ESG_MANAGER |
| reviewer@example.local | REVIEWER |
| management@example.local | MANAGEMENT |
| assessor@example.local | ASSESSOR |
| owner-alpha@example.local | DATA_OWNER (Plant Alpha) |
| owner-beta@example.local | DATA_OWNER (Plant Beta) |
| owner-gamma@example.local | DATA_OWNER (Plant Gamma) |
| owner-delta@example.local | DATA_OWNER (Plant Delta) |
| owner-projc@example.local | DATA_OWNER (Project C) |
| owner-eps@example.local | DATA_OWNER (Plant Epsilon) |

Seeded via `python -m app.seed` (idempotent; see Makefile `make seed`).
