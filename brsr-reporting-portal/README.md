# BRSR Reporting Portal

A metadata-driven BRSR (Business Responsibility and Sustainability Reporting) data-management and
reporting platform, built as a modular monolith with an async worker layer.

**Status: Phase 1 — Foundation.** Infrastructure stack (PostgreSQL, Redis, MinIO), FastAPI backend
with real health/readiness checks, and a Next.js frontend. Auth, framework engine, data collection,
validation, consolidation and reporting arrive in subsequent phases (see `docs/ARCHITECTURE.md`
once present).

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
