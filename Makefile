export UV_NO_EDITABLE := 1

.PHONY: install up down gate-1 lint typecheck test

install:
	uv sync --all-packages --frozen
	cd frontend && npm ci

up:
	docker compose up --build -d --wait

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
	bash infra/scripts/gate4.sh --repo-tests
	npm --prefix frontend test

.PHONY: gen-types
gen-types:
	PYTHONPATH=backend/src:edgar_pipeline/src:ml_pipeline/src .venv/bin/python infra/scripts/export_openapi.py
	cd frontend && ./node_modules/.bin/openapi-typescript ../backend/openapi.json -o src/api/generated/schema.d.ts

.PHONY: smoke gate-6
smoke:
	bash infra/scripts/smoke_test.sh

gate-6:
	bash infra/scripts/gate6.sh
