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

Introduced in the Auth phase.
