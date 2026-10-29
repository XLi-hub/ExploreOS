#!/usr/bin/env bash
# Package only the clean, revision-bound image and public installation files.
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
git diff --quiet
git diff --cached --quiet
REVISION="$(git rev-parse HEAD)"
IMAGE="exploreos:local"
IMAGE_REVISION="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE")"
if [ "$IMAGE_REVISION" != "$REVISION" ]; then
  echo 'Build this exact revision with --build-arg VCS_REF before packaging.' >&2
  exit 1
fi
DESTINATION="${1:-.runtime/distribution/exploreos-linux-amd64.tar.gz}"
mkdir -p -- "$(dirname -- "$DESTINATION")"
if [ -e "$DESTINATION" ] || [ -L "$DESTINATION" ]; then
  echo 'The destination already exists; choose a new product package path.' >&2
  exit 1
fi
PACKAGE_TEMP="$(mktemp -d "$(dirname -- "$DESTINATION")/.exploreos-package.XXXXXX")"
trap 'rm -rf -- "$PACKAGE_TEMP"' EXIT
mkdir "$PACKAGE_TEMP/bundle"
docker save "$IMAGE" | gzip -1 > "$PACKAGE_TEMP/bundle/exploreos-image.tar.gz"
cp compose.yaml .env.example "$PACKAGE_TEMP/bundle/"
cp docs/prebuilt-install.md "$PACKAGE_TEMP/bundle/README.md"
printf '%s\n' "$REVISION" > "$PACKAGE_TEMP/bundle/SOURCE_COMMIT.txt"
docker image inspect --format '{{.Id}}' "$IMAGE" > "$PACKAGE_TEMP/bundle/IMAGE_ID.txt"
(
  cd "$PACKAGE_TEMP/bundle"
  sha256sum exploreos-image.tar.gz compose.yaml .env.example README.md SOURCE_COMMIT.txt IMAGE_ID.txt > SHA256SUMS
)
tar -czf "$PACKAGE_TEMP/product.tar.gz" -C "$PACKAGE_TEMP/bundle" .
ln -- "$PACKAGE_TEMP/product.tar.gz" "$DESTINATION"
sha256sum "$DESTINATION"
