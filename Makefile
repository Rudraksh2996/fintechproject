.PHONY: install up down gate-1 lint typecheck test

install:
	uv sync --all-packages --frozen
	cd frontend && npm ci

up:
	docker compose up -d postgres neo4j

down:
	docker compose down

gate-1:
	bash infra/scripts/gate1.sh

lint:
	uv run --frozen ruff check .
	cd frontend && npm run lint

typecheck:
	uv run --frozen mypy --strict
	cd frontend && npm run typecheck

test:
	uv run --frozen pytest -q
