.PHONY: up down logs migrate seed test test-unit test-integration test-e2e lint format reset-db

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m app.seed

test:
	docker compose exec backend pytest tests -q

test-unit:
	docker compose exec backend pytest tests/unit -q

test-integration:
	docker compose exec backend pytest tests/integration -q

test-e2e:
	cd frontend && npx playwright test

lint:
	docker compose exec backend ruff check app tests
	cd frontend && npm run typecheck

format:
	docker compose exec backend ruff format app tests

reset-db:
	docker compose down -v
	docker compose up -d postgres redis minio
	make migrate seed
