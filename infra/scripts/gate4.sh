#!/usr/bin/env bash
# Use a new relational database and an ephemeral graph for write tests.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.orbstack/bin:$PWD/.venv/bin:$PATH"
free=$(df -Pk . | awk 'NR==2{print $4}')
(( free >= 5242880 )) || { echo "Less than 5 GiB free"; exit 1; }
docker info --format 'Docker {{.ServerVersion}} {{.Architecture}}'
docker compose up -d --wait postgres neo4j
scratch=$(mktemp -d)
export ARTIFACT_DIR="$scratch/artifacts"
mkdir "$ARTIFACT_DIR"
export PYTHONPATH="$PWD/backend/src:$PWD/edgar_pipeline/src:$PWD/ml_pipeline/src:$PWD/streamlit_workbench/src"
export UV_NO_EDITABLE=1
uv sync --all-packages --no-editable --frozen
export POSTGRES_DB="gate4_$$" REPLAY_ENABLED=false
graph="gate4-neo-$$"
api_pid=
st_pid=
created_db=false
cleanup() {
  if [[ -n "$st_pid" ]]; then kill "$st_pid" 2>/dev/null || true; fi
  if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; fi
  wait || true
  docker stop "$graph" >/dev/null 2>&1 || true
  if [[ "$created_db" == true ]]; then
    docker compose exec -T postgres sh -ec 'dropdb --force -U "$POSTGRES_USER" "$1"' sh "$POSTGRES_DB"
  fi
  rm -rf "$scratch"
}
trap cleanup EXIT
docker compose exec -T postgres sh -ec 'createdb -U "$POSTGRES_USER" "$1"' sh "$POSTGRES_DB"
created_db=true
alembic upgrade head
edgar seed-demo
edgar detect
docker compose run --rm --no-deps -T bootstrap tar -C /artifacts -cf - model.pt feature_scaler.json model_config.json metrics.json features.parquet scores.parquet ring_scores.parquet labels.parquet | tar -xf - -C "$ARTIFACT_DIR"
password=$(python -c 'import secrets; print(secrets.token_hex(16))')
export GATE4_TEST_NEO4J_AUTH="neo4j/$password"
docker run --rm -d --name "$graph" --memory 1050m -p 127.0.0.1::7687 \
  -e NEO4J_AUTH="$GATE4_TEST_NEO4J_AUTH" -e NEO4J_server_memory_heap_max__size=320m \
  -e NEO4J_server_memory_heap_initial__size=128m -e NEO4J_server_memory_pagecache_size=64m neo4j:5.26-community >/dev/null
port=$(docker port "$graph" 7687/tcp | awk -F: '{print $NF}')
export GATE4_TEST_NEO4J_URI="bolt://127.0.0.1:$port"
for _ in {1..60}; do
  if docker exec "$graph" cypher-shell -u neo4j -p "$password" 'RETURN 1' >/dev/null 2>&1; then break; fi
  sleep 1
done
ruff check .
mypy --strict
python -m pytest backend -q --disable-warnings --cov=app --cov-report=term-missing --cov-fail-under=80
free_port() {
  python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'
}
api_port=$(free_port)
export GATEWAY_URL="http://127.0.0.1:$api_port"
uvicorn app.main:create_app --factory --port "$api_port" >"$scratch/api.log" 2>&1 &
api_pid=$!
st_port=$(free_port)
streamlit run streamlit_workbench/app.py --server.headless=true --server.baseUrlPath=workbench \
  --server.address=127.0.0.1 --server.port="$st_port" >"$scratch/st.log" 2>&1 &
st_pid=$!
wait_http() {
  for _ in {1..60}; do
    if curl -fsS "$1" 2>/dev/null; then return 0; fi
    sleep 1
  done
  cat "$scratch/api.log" "$scratch/st.log" >&2
  return 1
}
wait_http "$GATEWAY_URL/api/v1/health" | python -c 'import json,sys; h=json.load(sys.stdin); assert h["model_loaded"] and h["status"]=="ok"; print(h)'
wait_http "http://127.0.0.1:$st_port/workbench/_stcore/health"
python -m pytest -q streamlit_workbench/tests
make gen-types
git diff --exit-code HEAD -- backend/openapi.json frontend/src/api/generated/schema.d.ts
echo 'Gate 4 PASSED'
