# BRSR Reporting Portal

A metadata-driven BRSR (Business Responsibility and Sustainability Reporting) data-management and
reporting platform, built as a modular monolith with an async worker layer.

**Status: feature-complete MVP.** All pipeline stages are implemented and integration-tested
(138 tests): auth/RBAC, entity hierarchy, metadata-driven BRSR framework (57 metrics, 2
versions, 16 BRSR Core indicators), collection with immutable value versioning, unit
normalization, 10-rule validation engine + statistical anomaly detection (IQR/z-score), safe
calculation engine, hierarchy consolidation with correct ratio recomputation, evidence with
SHA-256 + presigned downloads, click-through lineage, assurance readiness, period locking →
immutable snapshots → async PDF reports (Celery), live dashboard, lineage-aware trends, bulk
CSV import, notifications, and human-in-the-loop AI extraction. Docs: `docs/ARCHITECTURE.md`,
`docs/API.md`, `docs/DATABASE.md`, `docs/DEMO.md`, `docs/SECURITY.md`.

## One-command start

```bash
./run.sh          # fresh demo state: wipe → migrate → seed → consolidate → up → verify
./run.sh --keep   # keep data
./run.sh --test   # also run the backend test suite
```

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
