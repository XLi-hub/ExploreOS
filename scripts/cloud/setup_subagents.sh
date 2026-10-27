#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) { throw new Error("Pi requires Node >=22.19.0"); }'
mkdir -p .runtime/subagents
cp cloud/subagents/package.json .runtime/subagents/package.json
cp cloud/subagents/package-lock.json .runtime/subagents/package-lock.json
npm ci --prefix .runtime/subagents --ignore-scripts --no-audit --no-fund
node scripts/subagents_runner.mjs --check
echo "Pinned subagent runtime installed in this checkout. No global configuration or model request was used."
