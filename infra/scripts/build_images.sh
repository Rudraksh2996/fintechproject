#!/usr/bin/env bash
# Keep the laptop build on the data volume above the requested free-space floor.
set -euo pipefail
cd "$(dirname "$0")/../.."
check_disk() {
  local free_kib
  free_kib=$(df -Pk . | awk 'NR == 2 {print $4}')
  if (( free_kib < 5 * 1024 * 1024 )); then
    echo "Build stopped: only $free_kib KiB available (5 GiB minimum)." >&2
    return 1
  fi
}
check_disk
result=0
docker compose --profile tools build "$@" || result=$?
docker image prune -f
check_disk
exit "$result"
