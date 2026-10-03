#!/usr/bin/env bash
# =============================================================================
# BRSR Reporting Portal — MASTER RUN SCRIPT
#
# One command from zero to a fully demo-ready system:
#   ./run.sh              fresh start (wipes volumes, reseeds, consolidates)
#   ./run.sh --keep       keep existing data (migrate + consolidate only)
#   ./run.sh --test       additionally run the backend test suite
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="fresh"
RUN_TESTS="no"
for arg in "$@"; do
  case "$arg" in
    --keep) MODE="keep" ;;
    --test) RUN_TESTS="yes" ;;
    *) echo "unknown option: $arg (use --keep or --test)"; exit 1 ;;
  esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step() { echo -e "${CYAN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✔ $1${NC}"; }
info() { echo -e "${YELLOW}  $1${NC}"; }

# ---------------------------------------------------------------- environment
if [ ! -f .env ]; then
  step "No .env found — creating from .env.example"
  cp .env.example .env
  # local port overrides only needed if host ports 9000/9001 are busy
  if ss -tln 2>/dev/null | grep -qE ":(9000|9001) "; then
    info "host ports 9000/9001 busy — using 19000/19001 for MinIO"
    printf '\nMINIO_HOST_PORT=19000\nMINIO_CONSOLE_HOST_PORT=19001\n' >> .env
  fi
fi
MINIO_PORT=$(grep -E '^MINIO_HOST_PORT=' .env | cut -d= -f2 || true)
MINIO_PORT=${MINIO_PORT:-9000}

if [ "$MODE" = "fresh" ]; then
  step "Wiping volumes for a clean demo state"
  docker compose down -v --remove-orphans > /dev/null 2>&1 || true
else
  step "Stopping stack (keeping data)"
  docker compose down --remove-orphans > /dev/null 2>&1 || true
fi

# ------------------------------------------------------- datastores + health
step "Starting PostgreSQL, Redis, MinIO"
docker compose up -d postgres redis minio > /dev/null

wait_for() { # service, url
  for i in $(seq 1 40); do
    if curl -sf -o /dev/null "$2"; then return 0; fi
    sleep 1.5
  done
  echo "  ✗ $1 failed to become healthy"; docker compose logs "$1" --tail 20; exit 1
}
until docker compose exec -T postgres pg_isready -U brsr > /dev/null 2>&1; do sleep 1; done
until docker compose exec -T redis redis-cli ping > /dev/null 2>&1; do sleep 1; done
until curl -sf "http://localhost:${MINIO_PORT}/minio/health/live" > /dev/null 2>&1; do sleep 1; done
ok "PostgreSQL, Redis and MinIO are healthy"

# ----------------------------------------------------------------- migrations
step "Running database migrations"
docker compose run --rm backend alembic upgrade head > /dev/null 2>&1
ok "Schema is up to date"

# ---------------------------------------------------------------------- seed
step "Seeding entities, users, framework, periods and demo data"
docker compose run --rm backend python -m app.seed > /dev/null 2>&1
ok "Seed complete (15 entities, 11 users, 2 framework versions, 2 periods)"

# --------------------------------------- calculations + consolidation (both)
step "Computing derived metrics and consolidating the hierarchy"
docker compose run --rm backend python - <<'PY' > /dev/null 2>&1
from app.db.session import SessionLocal
from app.models import ReportingPeriod, AppUser
from sqlalchemy import select
from app.calculation import service as calc
from app.consolidation import service as cons
with SessionLocal() as db:
    user = db.scalar(select(AppUser).where(AppUser.email == "manager@example.local"))
    for label in ("FY2024-25", "FY2025-26"):
        period = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == label))
        if period is None:
            continue
        calc.run_calculations(db, period.id, actor=user)
        cons.run_consolidation(db, period.id, actor=user)
        db.commit()
PY
ok "Derived metrics computed, hierarchy consolidated for FY2024-25 and FY2025-26"

# ------------------------------------------------------------- full stack up
step "Starting backend, frontend and worker services"
docker compose up -d > /dev/null
wait_for "backend" "http://localhost:8000/healthz"
for i in $(seq 1 30); do
  READY=$(curl -s http://localhost:8000/readyz | python3 -c "import sys,json;print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
  [ "$READY" = "ready" ] && break
  sleep 1.5
done
[ "$READY" = "ready" ] || { echo "✗ backend not ready"; docker compose logs backend --tail 20; exit 1; }
ok "Backend ready (PostgreSQL + Redis + MinIO reachable)"
until curl -sf -o /dev/null http://localhost:3000; do sleep 1.5; done
ok "Frontend is up"

# ------------------------------------------------------------------- tests
if [ "$RUN_TESTS" = "yes" ]; then
  step "Running the backend test suite"
  docker compose exec -T backend pytest tests -q | tail -1
  ok "Tests passed"
fi

# ------------------------------------------------------------------- summary
MINIO_DISPLAY_PORT=$(docker compose port minio 9000 2>/dev/null | cut -d: -f2 || echo "$MINIO_PORT")
FRONTEND_PORT=$(docker compose port frontend 3000 2>/dev/null | cut -d: -f2 || echo "3000")
BACKEND_PORT=$(docker compose port backend 8000 2>/dev/null | cut -d: -f2 || echo "8000")

echo
echo -e "${GREEN}=============================================================${NC}"
echo -e "${GREEN}  BRSR Reporting Portal is running — demo ready${NC}"
echo -e "${GREEN}=============================================================${NC}"
echo -e "  Frontend      ${CYAN}http://localhost:${FRONTEND_PORT}${NC}"
echo -e "  API           ${CYAN}http://localhost:${BACKEND_PORT}${NC}   (docs: /docs)"
echo -e "  MinIO console ${CYAN}http://localhost:${MINIO_DISPLAY_PORT:-9001}${NC}"
echo
echo -e "  Demo accounts (password: ${YELLOW}Demo@12345${NC})"
echo -e "    admin@example.local        ADMIN"
echo -e "    manager@example.local      ESG_MANAGER   ← best demo login"
echo -e "    reviewer@example.local     REVIEWER"
echo -e "    owner-alpha@example.local  DATA_OWNER (Plant Alpha — +70% energy draft)"
echo -e "    management@example.local   MANAGEMENT"
echo -e "    assessor@example.local     ASSESSOR"
echo
echo -e "  Suggested flow: login as manager → dashboard → run validation on"
echo -e "  Exceptions page → review queue approvals → consolidation → assign"
echo -e "  owner submits 170,000 kWh → evidence upload → lock → report."
echo -e "${GREEN}=============================================================${NC}"
