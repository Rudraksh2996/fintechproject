#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export UV_NO_EDITABLE=1
uv sync --all-packages --frozen --no-editable --reinstall-package edgar-pipeline
docker compose up -d --wait --wait-timeout 180 postgres
uv run --frozen pytest -qs edgar_pipeline
uv run --frozen ruff check .
uv run --frozen mypy --strict
uv run --frozen python infra/scripts/verify_edgar.py
echo 'Gate 2 PASSED'
