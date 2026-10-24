#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
for executable in git python3 node npm; do
  command -v "$executable" >/dev/null || { echo "Missing prerequisite: $executable" >&2; exit 1; }
done
python3 - <<'PY'
import json,sys
from pathlib import Path
pins=json.loads(Path('cloud/versions.json').read_text())
minimum=tuple(map(int,pins['runtime']['python_minimum'].split('.')))
if sys.version_info[:2] < minimum:
    raise SystemExit('Configure Python '+pins['runtime']['python_minimum']+' or newer in the cloud environment.')
PY
node - <<'JS'
const fs=require('node:fs');
const pins=JSON.parse(fs.readFileSync('cloud/versions.json','utf8'));
if(Number(process.versions.node.split('.')[0]) < pins.runtime.node_minimum_major)
  throw new Error('Configure Node.js 22 or newer in the cloud environment.');
JS
mkdir -p "$PROJECT_ROOT/.runtime"
UPSTREAM_COMMIT="$(python3 -c 'import json; print(json.load(open("cloud/versions.json"))["upstream"]["commit"])')"
UPSTREAM_DIR="$PROJECT_ROOT/.runtime/upstream/AutoScientists"
NEW_UPSTREAM=0
if [ ! -d "$UPSTREAM_DIR" ]; then
  git clone --filter=blob:none --no-checkout --depth=1 https://github.com/mims-harvard/AutoScientists.git "$UPSTREAM_DIR"
  NEW_UPSTREAM=1
fi
if [ "$(git -C "$UPSTREAM_DIR" remote get-url origin)" != "https://github.com/mims-harvard/AutoScientists.git" ]; then
  echo "Unexpected upstream origin; inspect the existing runtime checkout." >&2; exit 1
fi
if [ "$NEW_UPSTREAM" = 0 ] && [ -n "$(git -C "$UPSTREAM_DIR" status --porcelain)" ]; then
  echo "Upstream runtime checkout has edits; preserve them before rerunning setup." >&2; exit 1
fi
git -C "$UPSTREAM_DIR" sparse-checkout set --no-cone '/README.md' '/requirements.txt' '/launch.py' '/runbook.md' '/system/'
git -C "$UPSTREAM_DIR" fetch --depth=1 origin "$UPSTREAM_COMMIT"
git -C "$UPSTREAM_DIR" checkout --detach "$UPSTREAM_COMMIT"
python3 -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -r cloud/requirements.txt
"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import hashlib,json,urllib.request
from pathlib import Path
pins=json.loads(Path('cloud/versions.json').read_text())['clawinstitute']
url='https://registry.npmjs.org/clawinstitute/-/clawinstitute-'+pins['version']+'.tgz'
with urllib.request.urlopen(url, timeout=60) as response:
    digest=hashlib.sha256(response.read()).hexdigest()
if digest != pins['tarball_sha256']:
    raise SystemExit('ClawInstitute release tarball differs from the audited package.')
PY
mkdir -p "$PROJECT_ROOT/.runtime/clawinstitute"
if [ -f "$PROJECT_ROOT/.runtime/clawinstitute/package.json" ] && ! cmp -s cloud/package.json "$PROJECT_ROOT/.runtime/clawinstitute/package.json"; then
  echo "Runtime manifest changed; create a fresh cloud task or deliberately reconcile its dependency cache." >&2; exit 1
fi
cp cloud/package.json "$PROJECT_ROOT/.runtime/clawinstitute/package.json"
if [ -f "$PROJECT_ROOT/.runtime/clawinstitute/package-lock.json" ]; then
  npm ci --prefix "$PROJECT_ROOT/.runtime/clawinstitute" --no-audit --no-fund
else
  npm install --prefix "$PROJECT_ROOT/.runtime/clawinstitute" --no-audit --no-fund
fi
node - <<'JS'
const fs=require('node:fs');
const pins=JSON.parse(fs.readFileSync('cloud/versions.json','utf8'));
const pkg=JSON.parse(fs.readFileSync('.runtime/clawinstitute/node_modules/clawinstitute/package.json','utf8'));
if(pkg.version !== pins.clawinstitute.version) throw new Error('Unexpected ClawInstitute version');
JS
"$PROJECT_ROOT/.venv/bin/python" -m pip freeze > "$PROJECT_ROOT/.runtime/python-installed.txt"
"$PROJECT_ROOT/.venv/bin/python" scripts/cloud/runtime.py doctor
echo "Bootstrap installed. Start services separately: .venv/bin/python scripts/cloud/runtime.py start"
echo "No model credentials, research agents, GPU jobs or background services were started by setup."
