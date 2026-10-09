.PHONY: demo demo-keep up down logs migrate seed test test-unit test-integration lint format reset-db

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
	@echo "Waiting for PostgreSQL …"
	@until docker compose exec -T postgres pg_isready -U brsr > /dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate seed

# ── Testing ─────────────────────────────────────────────────────────
test:
	docker compose exec backend pytest tests -v --tb=short

test-unit:
	docker compose exec backend pytest tests/unit -v --tb=short

test-integration:
	docker compose exec backend pytest tests/integration -v --tb=short

# ── Code quality ────────────────────────────────────────────────────
# NOTE: ruff is not currently in requirements.txt.
# To enable:  pip install ruff  (or add to requirements.txt and rebuild)
lint:
	@echo "Running TypeScript type-check …"
	cd frontend && npm run typecheck
	@echo ""
	@echo "NOTE: Python linting (ruff) is not installed in the backend image."
	@echo "      Add 'ruff' to backend/requirements.txt and rebuild to enable."

format:
	@echo "NOTE: ruff is not installed. Add to requirements.txt to enable."
	@echo "      cd frontend && npx prettier --write ."
