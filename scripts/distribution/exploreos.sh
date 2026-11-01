#!/usr/bin/env bash
# Run from a verified, prebuilt ExploreOS installation bundle.
set -euo pipefail
umask 077
BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$BUNDLE_ROOT"

usage() {
  cat <<'HELP'
ExploreOS · Linux amd64
Usage: bash exploreos.sh {start|stop|status|login|verify|help}
  start   Verify the bundle, load its exact image and start retained data.
  stop    Gracefully stop the service and keep all data volumes.
  status  Show container state and service/frontend health (no model call).
  login   Print the instance login token in this private terminal.
  verify  Check all package checksums without Docker or model calls.
HELP
}

verify_bundle() {
  if [ ! -f SHA256SUMS ]; then
    echo 'Run this helper from the extracted ExploreOS installation bundle.' >&2
    exit 1
  fi
  sha256sum -c SHA256SUMS
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo 'Install Docker Engine and Docker Compose v2 first.' >&2
    exit 1
  fi
  docker compose version >/dev/null
  docker info >/dev/null
}

load_exact_image() {
  local expected_image current_image
  expected_image="$(cat IMAGE_ID.txt)"
  current_image="$(docker image inspect --format '{{.Id}}' exploreos:local 2>/dev/null || true)"
  if [ "$current_image" != "$expected_image" ]; then
    docker load -i exploreos-image.tar.gz
    current_image="$(docker image inspect --format '{{.Id}}' exploreos:local)"
    if [ "$current_image" != "$expected_image" ]; then
      echo 'The loaded image does not match this package. Refusing to start.' >&2
      exit 1
    fi
  fi
}

case "${1:-help}" in
  help|--help|-h) usage ;;
  verify) verify_bundle ;;
  start)
    verify_bundle
    require_docker
    load_exact_image
    if [ ! -e .env ]; then
      (set -o noclobber; cat .env.example > .env)
      chmod 600 .env
    fi
    docker compose up --no-build -d --wait --wait-timeout 180
    echo 'ExploreOS: http://127.0.0.1:3001/api/v1/exploreos/ui'
    echo 'For the login token, run: bash exploreos.sh login'
    echo 'No exploration or model call has been started.'
    ;;
  stop)
    require_docker
    docker compose stop
    ;;
  status)
    require_docker
    docker compose ps
    docker compose exec -T exploreos .venv/bin/python scripts/cloud/product.py health
    ;;
  login)
    require_docker
    docker compose exec -T exploreos cat .runtime/service/home/token
    ;;
  *) usage >&2; exit 2 ;;
esac
