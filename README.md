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

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with the Compose v2 plugin
- `curl` (for health checks)
- `python3` (host — only for parsing readiness JSON; not needed inside containers)

## One-command start

```bash
./run.sh              # fresh demo state: wipe → build → migrate → seed → consolidate → up → verify
./run.sh --keep       # keep data, restart services, run migrations
./run.sh --test       # fresh start + run the complete backend test suite
./run.sh --keep --test  # keep data + run tests
./run.sh --stop       # stop frontend, backend, celery, and docker compose stack
./run.sh --stop -v    # stop stack and remove volumes (clean wipe)
```

The script:
1. Checks prerequisites (docker, curl)
2. Creates `.env` from `.env.example` (if missing) and auto-detects port conflicts
3. Builds container images
4. Starts infrastructure (PostgreSQL, Redis, RustFS)
5. Runs database migrations
6. Seeds demo data and computes derived metrics (fresh mode only)
7. Starts the full application stack
8. Verifies all services are healthy
9. (Optional) Runs the backend test suite

> **Port conflicts:** If ports 9000/9001 are occupied (by another project's storage),
> the script automatically uses 19000/19001 and updates `S3_PUBLIC_ENDPOINT` so that
> presigned evidence downloads work correctly from the browser.

## Quick start (manual)

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

## Services

| Service    | URL                    |
| ---------- | ---------------------- |
| Frontend   | http://localhost:3000  |
| Backend API| http://localhost:8000  |
| API docs   | http://localhost:8000/docs |
| Object storage console (RustFS) | http://localhost:9001 (or 19001 if redirected) |

## Verification

```bash
curl http://localhost:8000/healthz   # -> {"status":"ok"}
curl http://localhost:8000/readyz    # -> {"status":"ready","dependencies":{...}}
```

`/readyz` performs live checks against PostgreSQL, Redis and object storage (RustFS) and returns 503 when any
dependency is down.

## Makefile targets

```bash
make demo             # = ./run.sh
make demo-keep        # = ./run.sh --keep
make demo-test        # = ./run.sh --test
make up               # docker compose up --build -d
make down             # docker compose down
make logs             # docker compose logs -f
make migrate          # alembic upgrade head
make seed             # python -m app.seed
make test             # pytest tests (full suite)
make test-unit        # pytest tests/unit
make test-integration # pytest tests/integration
make reset-db         # wipe volumes, restart infra, re-migrate + reseed
make lint             # TypeScript type-check (ruff not yet in requirements)
```

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

Seeded via `python -m app.seed` (idempotent; see `make seed`).
