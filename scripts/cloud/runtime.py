#!/usr/bin/env python3
"""Manage only this checkout's development service; never launches research agents."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".runtime"
SERVICE = STATE / "service"
RECORD = SERVICE / "process.json"
TOKEN = SERVICE / "home" / "token"
ENTRY = STATE / "clawinstitute/node_modules/clawinstitute/bin/clawinstitute.js"


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def api(method: str, path: str, body=None, *, actor=None, headers=None, expected=None):
    record = json.loads(RECORD.read_text())
    target = f"http://127.0.0.1:{int(record['port'])}/api/v1{path}"
    request_headers = {
        "Authorization": "Bearer " + TOKEN.read_text().strip(),
        "Content-Type": "application/json",
    }
    if actor:
        request_headers["X-Agent-Name"] = actor
    request_headers.update(headers or {})
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(target, data=data, method=method, headers=request_headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, content = exc.code, exc.read()
    if expected is not None:
        if status != expected:
            raise RuntimeError(f"{method} {path}: expected HTTP {expected}, got {status}")
    elif not 200 <= status < 300:
        raise RuntimeError(f"{method} {path}: HTTP {status}")
    return json.loads(content) if content else {}


def alive(pid: int) -> bool:
    try:
        if Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z"):
            return False
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, FileNotFoundError):
        return False


def owned(record: dict) -> bool:
    pid = int(record["pid"])
    if not alive(pid):
        return False
    command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    return os.fsencode(str(ENTRY)) in command and Path(f"/proc/{pid}/cwd").resolve() == ROOT


@contextlib.contextmanager
def manager_lock():
    SERVICE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (SERVICE / "manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def doctor() -> None:
    if sys.platform != "linux":
        raise RuntimeError("This bootstrap targets Linux cloud environments.")
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required.")
    if not shutil.which("node"):
        raise RuntimeError("Node.js 22+ is required.")
    version = subprocess.check_output(["node", "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise RuntimeError("Node.js 22+ is required.")
    import requests  # noqa: F401
    import yaml  # noqa: F401
    pins = json.loads((ROOT / "cloud/versions.json").read_text())
    source = STATE / "upstream/AutoScientists"
    sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if sha != pins["upstream"]["commit"]:
        raise RuntimeError("Upstream checkout does not match cloud/versions.json.")
    package = json.loads((ENTRY.parents[1] / "package.json").read_text())
    if package["version"] != pins["clawinstitute"]["version"]:
        raise RuntimeError("ClawInstitute version mismatch.")
    if not (source / "runbook.md").is_file() or not (source / "system").is_dir():
        raise RuntimeError("Upstream sparse checkout is incomplete.")
    from patch_upstream import check_or_apply
    check_or_apply(check=True)
    print(json.dumps({"python": sys.version.split()[0], "node": version,
                      "upstream": sha, "clawinstitute": package["version"],
                      "atomic_file_patch": True, "idempotent_publication_patch": True, "native_exploration_patch": True,
                      "research_agents_started": False}, indent=2))


def start() -> None:
    doctor()
    with manager_lock():
        if RECORD.exists():
            record = json.loads(RECORD.read_text())
            if alive(int(record["pid"])):
                if not owned(record):
                    raise RuntimeError("Process record refers to another process; inspect it manually.")
                api("GET", "/workshops")
                print("This checkout's service is already ready.")
                return
            RECORD.unlink()
        port = int(os.environ.get("EXPLORE_API_PORT", "3000"))
        frontend_port = int(os.environ.get("EXPLORE_FRONTEND_PORT", "3001"))
        if not 1024 <= port <= 65535 or not 1024 <= frontend_port <= 65535:
            raise RuntimeError("Choose ports from 1024 to 65535.")
        if port == frontend_port:
            raise RuntimeError("API and frontend require different ports.")
        frontend_enabled = os.environ.get("EXPLORE_FRONTEND", "1") != "0"
        if frontend_enabled and port != 3000:
            raise RuntimeError("The pinned native UI rewrites to API port 3000; use that port or set EXPLORE_FRONTEND=0 for API-only tasks")
        with socket.socket() as probe:
            # Ignore closed connections in TIME_WAIT; active listeners still reject bind.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        if not TOKEN.exists():
            private_write(TOKEN, "claw_" + secrets.token_hex(32) + "\n")
        environment = os.environ.copy()
        environment.pop("DATABASE_URL", None)  # bootstrap always owns an isolated development DB
        environment.update({
            "PORT": str(port),
            "CLAWINSTITUTE_HOME": str(TOKEN.parent),
            "CLAWINSTITUTE_DB_DIR": str(SERVICE / "db"),
            "CLAWINSTITUTE_TOKEN": TOKEN.read_text().strip(),
            "CLAWINSTITUTE_AUTH_REQUIRED": "1",
            "CLAWINSTITUTE_CHECKPOINT_MS": "1000",
            "CLAWINSTITUTE_SKIP_FRONTEND": "0" if frontend_enabled else "1",
            "CLAWINSTITUTE_FRONTEND_PORT": str(frontend_port),
            "CLAWINSTITUTE_FRONTEND_HOSTNAME": "127.0.0.1",
            "EXPLOREOS_EXTENSION_PATH": str(ROOT / "cloud/native/exploreos.cjs"),
            "EXPLOREOS_ROOT": str(ROOT),
            "EXPLOREOS_PYTHON": str(ROOT / ".venv/bin/python"),
        })
        log_path = SERVICE / "server.log"
        with log_path.open("ab") as log:
            log_path.chmod(0o600)
            process = subprocess.Popen(
                ["node", str(ENTRY), "start"], cwd=ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        private_write(RECORD, json.dumps({"pid": process.pid, "port": port, "frontend_port": frontend_port,
                                         "frontend_enabled": frontend_enabled}) + "\n")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                RECORD.unlink(missing_ok=True)
                raise RuntimeError("Service exited; inspect the private .runtime/service/server.log.")
            try:
                api("GET", "/workshops")
                if frontend_enabled:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f"http://127.0.0.1:{frontend_port}/api/v1/exploreos/ui", timeout=2) as response:
                        if response.status != 200:
                            raise RuntimeError("Native exploration UI is not ready")
                print(f"ClawInstitute ready at http://127.0.0.1:{port}/api/v1 (authenticated).")
                if frontend_enabled:
                    print(f"Native ExploreOS view: http://127.0.0.1:{frontend_port}/api/v1/exploreos/ui")
                return
            except (OSError, RuntimeError, json.JSONDecodeError):
                time.sleep(0.5)
        raise RuntimeError("Service not ready after 60 seconds; inspect private logs, then run stop.")


def stop() -> None:
    with manager_lock():
        if not RECORD.exists():
            print("No managed service record.")
            return
        record = json.loads(RECORD.read_text())
        pid = int(record["pid"])
        if alive(pid):
            if not owned(record):
                raise RuntimeError("Refusing to signal an unrelated process.")
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 20
            while alive(pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            if alive(pid):
                raise RuntimeError("Graceful stop timed out; no force-kill was issued.")
        RECORD.unlink(missing_ok=True)
        print("Managed service stopped; development data retained.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["doctor", "start", "stop", "status"])
    command = parser.parse_args().command
    if command == "status":
        if not RECORD.exists():
            raise RuntimeError("Managed service has not been started.")
        record = json.loads(RECORD.read_text())
        if not owned(record):
            raise RuntimeError("Managed process is not running.")
        api("GET", "/workshops")
        print("Managed service is running and authenticated.")
    else:
        {"doctor": doctor, "start": start, "stop": stop}[command]()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
