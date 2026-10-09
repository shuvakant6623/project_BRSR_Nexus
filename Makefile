.PHONY: demo demo-keep demo-test up down logs migrate seed reset-db test test-unit test-integration lint format

# ── One-command demo ────────────────────────────────────────────────
demo:
	./run.sh

demo-keep:
	./run.sh --keep

demo-test:
	./run.sh --test

# ── Manual lifecycle ────────────────────────────────────────────────
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

# ── Database ────────────────────────────────────────────────────────
migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m app.seed

reset-db:
	docker compose down -v
	docker compose up -d postgres redis s3
	docker compose run --rm backend alembic upgrade head
	docker compose run --rm backend python -m app.seed

# ── Testing ─────────────────────────────────────────────────────────
test:
	docker compose exec backend pytest tests -v --tb=short

test-unit:
	docker compose exec backend pytest tests/unit -v --tb=short

test-integration:
	docker compose exec backend pytest tests/integration -v --tb=short

# ── Code quality ────────────────────────────────────────────────────
# ruff ships in the backend image (backend/ruff.toml configures the rules).
lint:
	docker compose exec backend ruff check app tests
	cd frontend && npm run typecheck

format:
	docker compose exec backend ruff format app tests
