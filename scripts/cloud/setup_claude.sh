#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p .runtime/claude-probe
cp cloud/claude/package.json .runtime/claude-probe/package.json
cp cloud/claude/package-lock.json .runtime/claude-probe/package-lock.json
npm ci --prefix .runtime/claude-probe --no-audit --no-fund
.runtime/claude-probe/node_modules/.bin/claude --version
echo "Pinned CLI installed in this checkout. No provider key or model request was used."
