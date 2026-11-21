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

.PHONY: gen-types
gen-types:
	PYTHONPATH=backend/src:edgar_pipeline/src:ml_pipeline/src .venv/bin/python infra/scripts/export_openapi.py
	cd frontend && ./node_modules/.bin/openapi-typescript ../backend/openapi.json -o src/api/generated/schema.d.ts
