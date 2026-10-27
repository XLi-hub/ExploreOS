#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) { throw new Error("Pi requires Node >=22.19.0"); }'
mkdir -p .runtime/pi
cp cloud/pi/package.json .runtime/pi/package.json
cp cloud/pi/package-lock.json .runtime/pi/package-lock.json
npm ci --prefix .runtime/pi --ignore-scripts --no-audit --no-fund
node scripts/pi_runner.mjs --check
echo "Pinned Pi libraries installed in this checkout. No provider key or model request was used."
