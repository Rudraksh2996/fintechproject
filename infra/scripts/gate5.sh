#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.orbstack/bin:$PATH"
free=$(df -Pk . | awk 'NR==2{print $4}')
((free>=5242880)) || { echo 'Less than 5 GiB free'; exit 1; }
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
if rg -in '(from|import\()[^[:cntrl:]]*(fixtures/|__mocks__/)|lorem ipsum' frontend/src; then
  echo 'Disallowed fixture, mock or placeholder display content'; exit 1
fi
make gen-types
git diff --exit-code -- backend/openapi.json frontend/src/api/generated/schema.d.ts
docker compose up -d --no-build --wait frontend
docker compose exec -T streamlit python /tmp/check_workbench_image.py
docker compose exec -T backend uv pip check
export GATE_COLD_ACCOUNT
GATE_COLD_ACCOUNT=$(docker compose exec -T backend python - <<'PY'
from ml_pipeline.config import GraphSettings
from neo4j import GraphDatabase
config = GraphSettings()
with GraphDatabase.driver(config.neo4j_uri, auth=tuple(config.neo4j_auth.get_secret_value().split("/", 1))) as driver, driver.session() as session:
    row=session.run("MATCH (a:Account) WITH a, COUNT { (a)-[:TRANSFERRED]-() } AS n WHERE n < 10 RETURN a.account_id AS id LIMIT 1").single(strict=True)
    print(row["id"])
PY
)
node frontend/tests/routes.mjs
echo 'Gate 5 PASSED'
