#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if ! command -v docker >/dev/null 2>&1; then
  echo 'Gate 1 BLOCKED: Docker is required; no database checks were run.' >&2
  exit 127
fi
docker compose version
docker compose up -d --wait --wait-timeout 180 postgres neo4j
docker compose --profile tools build schema
docker compose --profile tools run --rm schema
docker compose --profile tools run --rm schema /platform/.venv/bin/alembic downgrade base
docker compose --profile tools run --rm schema
docker compose exec -T neo4j sh -c 'auth="$NEO4J_AUTH"; cypher-shell -u "${auth%%/*}" -p "${auth#*/}" -f /schema/constraints.cypher'
docker compose exec -T neo4j sh -c 'auth="$NEO4J_AUTH"; cypher-shell -u "${auth%%/*}" -p "${auth#*/}" "SHOW CONSTRAINTS"'
docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT conname FROM pg_constraint WHERE conname = '\''uq_form4_accession_line'\''; SELECT indexname FROM pg_indexes WHERE indexname = '\''ix_form4_ticker_date'\'';"'
echo 'Checking PostgreSQL and Neo4j definitions and workbench_ro INSERT permissions'
docker compose --profile tools run --rm schema /platform/.venv/bin/python infra/scripts/verify_schema.py
uv run --frozen ruff check .
uv run --frozen mypy --strict
uv run --frozen pytest -q
(cd frontend && npm run lint && npm run typecheck)
echo 'Gate 1 PASSED'
