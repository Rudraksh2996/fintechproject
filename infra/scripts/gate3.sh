#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export UV_NO_EDITABLE=1
uv sync --all-packages --no-editable --frozen --reinstall-package ml-pipeline
docker compose up -d --wait neo4j
uv run --frozen pytest -q ml_pipeline
uv run --frozen ruff check .
uv run --frozen mypy --strict
bash infra/scripts/build_images.sh bootstrap
# Persist each stage on the project artifact volume for downstream inference.
for stage in generate load features; do
  docker compose --profile tools run --rm bootstrap mule "$stage" --output /artifacts
done
docker compose --profile tools run --rm bootstrap python -m ml_pipeline.gnn.train /artifacts
docker compose --profile tools run --rm bootstrap python /platform/verify_model.py /artifacts
echo 'Gate 3 PASSED'
