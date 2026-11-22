#!/usr/bin/env bash
# Destructive release gate: reset this Compose project's volumes and test committed main.
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$PWD
export PATH="$HOME/.orbstack/bin:$PATH" UV_NO_EDITABLE=1
free=$(df -Pk . | awk 'NR==2{print $4}')
(( free >= 5242880 )) || { echo 'Less than 5 GiB free'; exit 1; }
project=$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
export COMPOSE_PROJECT_NAME="$project"
test "$(git rev-parse HEAD)" = "$(git rev-parse main)" || { echo 'Check out the main revision to verify'; exit 1; }
scratch=$(mktemp -d)
echo "Fresh checkout: $scratch/checkout; Compose project: $project"
# A real Git transport includes only committed blobs, even for a local release candidate.
git clone --no-local --branch main --single-branch "$root" "$scratch/checkout"
(
    cd "$scratch/checkout"
    test -z "$(git status --porcelain)"
    git rev-parse HEAD
    cp .env.example .env
    docker info --format 'Docker {{.ServerVersion}} {{.Architecture}}'
    docker compose down -v
    python3 infra/scripts/checked_build.py up --build -d --wait --wait-timeout 1500
    docker compose ps -a
    for service in bootstrap ml-base; do
        id=$(docker compose ps -aq "$service")
        test "$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$id")" = 'exited 0'
    done
    make smoke
    mkdir -p docs/screenshots
    python3 infra/scripts/checked_build.py --profile e2e build e2e
    docker compose --profile e2e run --no-deps --rm e2e
    for view in command-center insider-radar mule-explorer workbench; do
        test -s "docs/screenshots/$view.png"
        cp "docs/screenshots/$view.png" "$root/docs/screenshots/$view.png"
    done
)
# Rebind mounted config files to the durable working tree before disposing of the checkout.
docker compose up -d --no-build --wait
uv run --frozen python infra/scripts/live_day.py
make lint typecheck test
df -h .
echo 'Gate 6 PASSED'
