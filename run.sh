#!/usr/bin/env bash
# =============================================================================
# BRSR Reporting Portal — MASTER RUN SCRIPT
#
# Control commands:
#   ./run.sh              fresh start (wipes volumes, reseeds, consolidates)
#   ./run.sh --keep       keep existing data (migrate + restart only)
#   ./run.sh --test       additionally run the backend test suite
#   ./run.sh --stop       stop frontend, backend, celery, and docker containers
#   ./run.sh --stop -v    stop containers and remove volumes (clean wipe)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# ------------------------------------------------------------------ arguments
MODE="fresh"
RUN_TESTS="no"
STOP_ONLY="no"
STOP_VOLUMES="no"

for arg in "$@"; do
  case "$arg" in
    --keep) MODE="keep" ;;
    --test) RUN_TESTS="yes" ;;
    --stop) STOP_ONLY="yes" ;;
    -v|--volumes) STOP_VOLUMES="yes" ;;
    -h|--help)
      echo "BRSR Reporting Portal — Control Script"
      echo ""
      echo "Usage: ./run.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  (no args)     Fresh start (rebuilds images, wipes volumes, reseeds, consolidates)"
      echo "  --keep        Keep existing data (migrate + restart only)"
      echo "  --test        Additionally run the backend test suite after starting"
      echo "  --stop        Stop frontend, backend, celery, and docker compose stack"
      echo "  --stop -v     Stop containers and remove volumes (clean wipe)"
      echo "  -h, --help    Show this help message"
      exit 0
      ;;
    *) echo "Unknown option: $arg (use --keep, --test, --stop, or --help)"; exit 1 ;;
  esac
done

# ------------------------------------------------------------------ colours
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m';  NC='\033[0m'

# ------------------------------------------------------------------ stop handler
if [ "$STOP_ONLY" = "yes" ]; then
  echo -e "${CYAN}Stopping BRSR Reporting Portal stack...${NC}"

  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    if [ "$STOP_VOLUMES" = "yes" ]; then
      echo -e "  ${YELLOW}ℹ Stopping containers and removing volumes...${NC}"
      docker compose down -v --remove-orphans 2>&1 | sed 's/^/  /' || true
      echo -e "  ${GREEN}✔ Docker containers and volumes removed${NC}"
    else
      echo -e "  ${YELLOW}ℹ Stopping and removing containers (keeping volumes)...${NC}"
      docker compose down --remove-orphans 2>&1 | sed 's/^/  /' || true
      echo -e "  ${GREEN}✔ Docker containers stopped and removed${NC}"
    fi
  else
    echo -e "  ${YELLOW}ℹ Docker or docker compose not available${NC}"
  fi

  # Stop any stray local processes that may have been started on host ports
  if command -v pkill &>/dev/null; then
    pkill -f "uvicorn app.main:app" 2>/dev/null && echo -e "  ${GREEN}✔ Local uvicorn processes terminated${NC}" || true
    pkill -f "celery -A app.workers.celery_app" 2>/dev/null && echo -e "  ${GREEN}✔ Local celery processes terminated${NC}" || true
  fi

  echo
  echo -e "${GREEN}=============================================================${NC}"
  echo -e "${GREEN}  All services (frontend, backend, celery, docker) stopped.${NC}"
  echo -e "${GREEN}=============================================================${NC}"
  exit 0
fi

STEP_NO=0
TOTAL_STEPS=8
if [ "$RUN_TESTS" = "yes" ]; then TOTAL_STEPS=9; fi

step() { STEP_NO=$((STEP_NO + 1)); echo -e "${CYAN}[${STEP_NO}/${TOTAL_STEPS}] $1${NC}"; }
ok()   { echo -e "  ${GREEN}✔ $1${NC}"; }
info() { echo -e "  ${YELLOW}ℹ $1${NC}"; }
fail() { echo -e "  ${RED}✗ $1${NC}"; }

die() {
  fail "$1"
  if [ -n "${2:-}" ]; then
    echo -e "  ${YELLOW}Hint: $2${NC}"
  fi
  exit 1
}

# --------------------------------------------------------- prerequisite check
step "Checking prerequisites"

for cmd in docker curl; do
  if ! command -v "$cmd" &>/dev/null; then
    die "'$cmd' is required but not found." "Install $cmd and try again."
  fi
done

if ! docker compose version &>/dev/null; then
  die "'docker compose' plugin is required." \
      "Install Docker Compose v2: https://docs.docker.com/compose/install/"
fi

if ! docker info &>/dev/null; then
  die "Docker daemon is not running." "Start Docker and try again."
fi

ok "docker, docker compose, curl — available"

# --------------------------------------------------------- environment setup
step "Preparing environment"

# Detect host ports for object storage
S3_HOST_PORT=9000
S3_CONSOLE_HOST_PORT=9001

if command -v ss &>/dev/null; then
  PORT_CHECK_CMD="ss -tln"
elif command -v netstat &>/dev/null; then
  PORT_CHECK_CMD="netstat -tln"
else
  PORT_CHECK_CMD=""
fi

if [ -n "$PORT_CHECK_CMD" ]; then
  if $PORT_CHECK_CMD 2>/dev/null | grep -qE ":(9000|9001) "; then
    S3_HOST_PORT=19000
    S3_CONSOLE_HOST_PORT=19001
    info "Ports 9000/9001 occupied — using ${S3_HOST_PORT}/${S3_CONSOLE_HOST_PORT} for object storage"
  fi
fi

if [ ! -f .env ]; then
  info "No .env found — creating from .env.example"
  cp .env.example .env
fi

# Deterministic env-var update: sed in-place, never append duplicates.
# Update storage host ports
_env_set() {
  # Sets KEY=VALUE in .env, creating or updating in place.
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    echo "${key}=${value}" >> .env
  fi
}

_env_set "MINIO_HOST_PORT" "$S3_HOST_PORT"
_env_set "MINIO_CONSOLE_HOST_PORT" "$S3_CONSOLE_HOST_PORT"
_env_set "S3_PUBLIC_ENDPOINT" "http://localhost:${S3_HOST_PORT}"

# Read back the resolved port for health checks
S3_HOST_PORT=$(grep -E '^MINIO_HOST_PORT=' .env | cut -d= -f2)

ok "Environment configured (S3 on host port ${S3_HOST_PORT})"

# --------------------------------------------------------- teardown / rebuild
if [ "$MODE" = "fresh" ]; then
  step "Wiping volumes for a clean demo state"
  docker compose down -v --remove-orphans 2>&1 | tail -n 3 || true
  ok "Volumes removed"
else
  step "Stopping stack (keeping data)"
  docker compose down --remove-orphans 2>&1 | tail -n 3 || true
  ok "Stack stopped"
fi

# --------------------------------------------------------- build images
step "Building container images (if needed)"
if ! docker compose build 2>&1 | tail -n 5; then
  die "Image build failed." "Check Dockerfile syntax and network connectivity."
fi
ok "Images ready"

# ----------------------------------------------------- start infrastructure
step "Starting PostgreSQL, Redis, RustFS (object storage)"
docker compose up -d postgres redis s3

# --- Postgres readiness (max 60 s)
PG_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2 || echo "brsr")
for i in $(seq 1 40); do
  if docker compose exec -T postgres pg_isready -U "$PG_USER" &>/dev/null; then break; fi
  if [ "$i" -eq 40 ]; then
    fail "PostgreSQL did not become ready in 60 s"
    docker compose logs postgres --tail 15
    exit 1
  fi
  sleep 1.5
done
ok "PostgreSQL is healthy"

# --- Redis readiness (max 30 s)
for i in $(seq 1 20); do
  if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then break; fi
  if [ "$i" -eq 20 ]; then
    fail "Redis did not respond PONG in 30 s"
    docker compose logs redis --tail 15
    exit 1
  fi
  sleep 1.5
done
ok "Redis is healthy"

# --- RustFS / S3 readiness (max 60 s)
# Try the MinIO-compatible health endpoint first, then fall back to a raw
# TCP-level HTTP probe.  RustFS may or may not expose /minio/health/live.
for i in $(seq 1 40); do
  if curl -sf "http://localhost:${S3_HOST_PORT}/minio/health/live" -o /dev/null 2>/dev/null; then break; fi
  if curl -sf "http://localhost:${S3_HOST_PORT}/" -o /dev/null 2>/dev/null; then break; fi
  # Also accept a 403 — means the port is up and serving S3 (just no anon access)
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${S3_HOST_PORT}/" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "403" ] || [ "$HTTP_CODE" = "200" ]; then break; fi
  if [ "$i" -eq 40 ]; then
    fail "Object storage (RustFS) not reachable on port ${S3_HOST_PORT} after 60 s"
    docker compose logs s3 --tail 15
    exit 1
  fi
  sleep 1.5
done
ok "RustFS (S3) is healthy on port ${S3_HOST_PORT}"

# --------------------------------------------------------- migrations
step "Running database migrations"
if ! docker compose run --rm backend alembic upgrade head 2>&1; then
  die "Migration failed." "Check backend/migrations/ and database connectivity."
fi
ok "Schema is up to date"

# --------------------------------------------------------- seed + calculate
step "Seeding demo data and computing derived metrics"

if [ "$MODE" = "fresh" ]; then
  # Seed
  if ! docker compose run --rm backend python -m app.seed 2>&1; then
    die "Seed failed." "Check backend/app/seed.py for errors."
  fi
  ok "Seed complete (15 entities, 11 users, 2 framework versions, 2 periods)"

  # Calculate + Consolidate
  if ! docker compose run --rm backend python -c "
from app.db.session import SessionLocal
from app.models import ReportingPeriod, AppUser
from sqlalchemy import select
from app.calculation import service as calc
from app.consolidation import service as cons

with SessionLocal() as db:
    user = db.scalar(select(AppUser).where(AppUser.email == 'manager@example.local'))
    if user is None:
        raise RuntimeError('Seed error: manager@example.local not found')
    for label in ('FY2024-25', 'FY2025-26'):
        period = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label == label))
        if period is None:
            print(f'  Skipping {label} — not found')
            continue
        calc.run_calculations(db, period.id, actor=user)
        cons.run_consolidation(db, period.id, actor=user)
        db.commit()
        print(f'  Calculated + consolidated {label}')
" 2>&1; then
    die "Calculation/consolidation failed." \
        "Ensure seed ran successfully and check calculation/consolidation services."
  fi
  ok "Derived metrics computed, hierarchy consolidated"
else
  info "Keep mode — running migrations only (seed + calculations skipped)"
  # Still run migrations in case schema changed
fi

# ---------------------------------------------------------- full stack up
step "Starting application stack"
docker compose up -d 2>&1 | tail -n 5

# --- Backend readiness
for i in $(seq 1 40); do
  if curl -sf "http://localhost:8000/healthz" -o /dev/null 2>/dev/null; then break; fi
  if [ "$i" -eq 40 ]; then
    fail "Backend /healthz not reachable after 60 s"
    docker compose logs backend --tail 20
    exit 1
  fi
  sleep 1.5
done

READY=""
for i in $(seq 1 30); do
  READY=$(curl -s http://localhost:8000/readyz 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
  if [ "$READY" = "ready" ]; then break; fi
  sleep 1.5
done
if [ "$READY" != "ready" ]; then
  fail "Backend /readyz did not report 'ready' — dependencies may be down"
  curl -s http://localhost:8000/readyz 2>/dev/null || true
  echo
  docker compose logs backend --tail 20
  exit 1
fi
ok "Backend ready (all dependencies connected)"

# --- Frontend readiness
for i in $(seq 1 30); do
  if curl -sf "http://localhost:3000" -o /dev/null 2>/dev/null; then break; fi
  if [ "$i" -eq 30 ]; then
    fail "Frontend not reachable on port 3000 after 45 s"
    docker compose logs frontend --tail 15
    exit 1
  fi
  sleep 1.5
done
ok "Frontend is up"

# --- Celery worker check
WORKER_UP="no"
for i in $(seq 1 10); do
  if docker compose exec -T celery-worker celery -A app.workers.celery_app.celery_app inspect ping --timeout 3 &>/dev/null; then
    WORKER_UP="yes"
    break
  fi
  sleep 2
done
if [ "$WORKER_UP" = "yes" ]; then
  ok "Celery worker is running"
else
  info "Celery worker may still be initialising (non-blocking)"
fi

# ---------------------------------------------------------- test suite
if [ "$RUN_TESTS" = "yes" ]; then
  step "Running backend test suite"

  # Capture full pytest output, parse results, and propagate exit code
  set +e
  TEST_OUTPUT=$(docker compose exec -T backend pytest tests -v --tb=short 2>&1)
  TEST_EXIT=$?
  set -e

  echo "$TEST_OUTPUT"
  echo

  # Parse pytest summary line (e.g. "138 passed, 1 failed, 2 skipped")
  SUMMARY=$(echo "$TEST_OUTPUT" | grep -E '^\s*(=+|FAILED|PASSED|ERROR)' | tail -1)
  PASSED=$(echo "$TEST_OUTPUT" | grep -oP '\d+ passed' | head -1 || echo "0 passed")
  FAILED=$(echo "$TEST_OUTPUT" | grep -oP '\d+ failed' | head -1 || echo "")
  SKIPPED=$(echo "$TEST_OUTPUT" | grep -oP '\d+ skipped' | head -1 || echo "")

  echo -e "${CYAN}Test Summary:${NC}"
  echo -e "  Passed:  ${GREEN}${PASSED}${NC}"
  if [ -n "$FAILED" ]; then
    echo -e "  Failed:  ${RED}${FAILED}${NC}"
  else
    echo -e "  Failed:  ${GREEN}0 failed${NC}"
  fi
  if [ -n "$SKIPPED" ]; then
    echo -e "  Skipped: ${YELLOW}${SKIPPED}${NC}"
  fi
  echo

  if [ "$TEST_EXIT" -ne 0 ]; then
    die "Test suite failed (exit code ${TEST_EXIT})." \
        "Review the output above for failing tests."
  fi
  ok "All tests passed"
fi

# ---------------------------------------------------------- summary
S3_DISPLAY_PORT=$(docker compose port s3 9000 2>/dev/null | cut -d: -f2 || echo "$S3_HOST_PORT")
S3_CONSOLE_DISPLAY_PORT=$(docker compose port s3 9001 2>/dev/null | cut -d: -f2 || echo "$S3_CONSOLE_HOST_PORT")
FRONTEND_PORT=$(docker compose port frontend 3000 2>/dev/null | cut -d: -f2 || echo "3000")
BACKEND_PORT=$(docker compose port backend 8000 2>/dev/null | cut -d: -f2 || echo "8000")

echo
echo -e "${GREEN}=============================================================${NC}"
echo -e "${GREEN}  BRSR Reporting Portal is running — demo ready${NC}"
echo -e "${GREEN}=============================================================${NC}"
echo
echo -e "  ${CYAN}Frontend${NC}          http://localhost:${FRONTEND_PORT}"
echo -e "  ${CYAN}API${NC}               http://localhost:${BACKEND_PORT}       (docs: /docs)"
echo -e "  ${CYAN}Storage Console${NC}   http://localhost:${S3_CONSOLE_DISPLAY_PORT}"
echo
echo -e "  ${CYAN}Services:${NC}"
echo -e "    PostgreSQL:   ${GREEN}healthy${NC}"
echo -e "    Redis:        ${GREEN}healthy${NC}"
echo -e "    RustFS (S3):  ${GREEN}healthy${NC}   (port ${S3_DISPLAY_PORT})"
echo -e "    Backend:      ${GREEN}ready${NC}"
echo -e "    Celery:       ${GREEN}running${NC}"
echo -e "    Frontend:     ${GREEN}ready${NC}"
echo
echo -e "  Demo accounts (password: ${YELLOW}Demo@12345${NC})"
echo -e "    admin@example.local        ADMIN"
echo -e "    manager@example.local      ESG_MANAGER   ← best demo login"
echo -e "    reviewer@example.local     REVIEWER"
echo -e "    owner-alpha@example.local  DATA_OWNER (Plant Alpha)"
echo -e "    management@example.local   MANAGEMENT"
echo -e "    assessor@example.local     ASSESSOR"
echo
echo -e "  Suggested flow: login as manager → dashboard → run validation on"
echo -e "  Exceptions page → review queue approvals → consolidation → assign"
echo -e "  owner submits 170,000 kWh → evidence upload → lock → report."
echo -e "${GREEN}=============================================================${NC}"
