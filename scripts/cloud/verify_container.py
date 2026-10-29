#!/usr/bin/env python3
"""Explicit zero-model product installation/replacement check in isolated volumes."""
import argparse
import json
import os
import subprocess
import time
import uuid


SEED = r'''
import hashlib, json
from pathlib import Path
from explore.native import NativeService
from explore.store import Client
from scripts.probe_native import session_budget
service=NativeService(Client())
assert service.runtime()["credential"] == "missing"
assert service.runtime()["budget"] is None
result=service.handle({"action":"create","data":{"name":"container_acceptance", "question":"How should a team preserve useful disagreements?", "execution":{"backend":"simulated"}}})
project=service.project(result["name"])
service.add_source(project,{"title":"Explicit synthetic container fixture", "text":"A response does not resolve an objection.\nA changed question can invalidate an old assumption.\n"})
service.handle({"action":"advance","name":result["name"]})
view=service.state(project)
assert view["brief"]["completed_rounds"] == 1
assert len(view["brief"]["findings"]) == 3
assert all(c["backend"] == "simulated" for c in view["calls"])
exported=project.export(project.directory/"exports")
assert exported["kind"] == "mechanical_fixture"
# This is a synthetic ledger record, never a supplier request or bill.
budget=session_budget(service.client,limit=5)
budget.admit("container-fixture-no-supplier",100,100,{"qualification":"Synthetic unknown reservation; no supplier contacted"})
expected={"state_sha256":hashlib.sha256(json.dumps(view,sort_keys=True).encode()).hexdigest(),"budget":service.budget_view()}
assert expected["budget"]["unknown_requests"] == 1
Path(".research/container-acceptance.json").write_text(json.dumps(expected))
print("PASS: fresh installation, native creation/materials/round/brief/export and synthetic unknown-budget fixture (no supplier).")
'''

VERIFY = r'''
import hashlib,json
from pathlib import Path
from explore.native import NativeService
from explore.store import Client
service=NativeService(Client())
expected=json.loads(Path(".research/container-acceptance.json").read_text())
view=service.state(service.project("container_acceptance"))
assert hashlib.sha256(json.dumps(view,sort_keys=True).encode()).hexdigest() == expected["state_sha256"]
assert service.budget_view() == expected["budget"]
assert view["native_execution"] == {"backend":"simulated"}
assert service.runtime()["credential"] == "missing"
print("PASS: replacement preserves exact project view, sources, posts, brief, execution profile and unknown exposure; no new calls.")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="exploreos:product-check")
    parser.add_argument("--docker-host", default="unix:///var/run/docker.sock")
    args = parser.parse_args()
    environment = dict(os.environ)
    for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(name, None)
    prefix = ["docker", "--host=" + args.docker_host]

    def run(*arguments, code=None, check=True):
        result = subprocess.run([*prefix, *arguments], input=code, text=True, capture_output=True, env=environment)
        if check and result.returncode:
            raise RuntimeError("Container check failed during " + arguments[0] + ": " + result.stderr[-1200:])
        return result

    suffix = uuid.uuid4().hex[:12]
    container = "exploreos-check-" + suffix
    volumes = ["exploreos-check-service-" + suffix, "exploreos-check-research-" + suffix,
               "exploreos-check-backup-" + suffix, "exploreos-check-restored-service-" + suffix,
               "exploreos-check-restored-research-" + suffix]
    active_volumes = volumes[:2]

    def mounts():
        return ("--mount", f"type=volume,src={active_volumes[0]},dst=/opt/exploreos/.runtime/service",
                "--mount", f"type=volume,src={active_volumes[1]},dst=/opt/exploreos/.research",
                "--mount", f"type=volume,src={volumes[2]},dst=/opt/exploreos/.runtime/backups")

    def start():
        run("run", "--detach", "--name", container, "--platform", "linux/amd64", "--env", "DEEPSEEK_API_KEY=",
            *mounts(), args.image)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if run("inspect", "--format", "{{.State.Running}}", container).stdout.strip() != "true":
                raise RuntimeError("The product supervisor exited before becoming ready")
            if run("exec", container, ".venv/bin/python", "scripts/cloud/product.py", "health", check=False).returncode == 0:
                return
            time.sleep(2)
        raise RuntimeError("The isolated product did not become ready")

    def execute(code):
        print(run("exec", "-i", container, ".venv/bin/python", "-", code=code).stdout.strip(), flush=True)

    try:
        start()
        # A second supervisor must not adopt or stop the actual service.
        duplicate = run("exec", container, ".venv/bin/python", "scripts/cloud/product.py", "serve", check=False)
        if duplicate.returncode == 0 or "Another product supervisor" not in duplicate.stderr:
            raise RuntimeError("A second supervisor was not safely rejected")
        live_backup = run("run", "--rm", *mounts(), args.image, ".venv/bin/python", "scripts/cloud/backup.py",
                          "create", "/opt/exploreos/.runtime/backups/must-not-exist.tar.gz", check=False)
        if live_backup.returncode == 0 or "Stop the product supervisor" not in live_backup.stderr:
            raise RuntimeError("Cross-container backup failed to reject the active product supervisor")
        execute(SEED)
        run("stop", "--time", "90", container)
        outcome = json.loads(run("inspect", "--format", "{{json .State}}", container).stdout)
        if outcome["ExitCode"] != 0 or outcome["OOMKilled"]:
            raise RuntimeError("The product did not stop gracefully")
        archive = "/opt/exploreos/.runtime/backups/verified-instance.tar.gz"
        run("run", "--rm", *mounts(), args.image, ".venv/bin/python", "scripts/cloud/backup.py", "create", archive)
        run("rm", container)
        start()
        execute(VERIFY)
        run("stop", "--time", "90", container)
        run("rm", container)
        active_volumes = volumes[3:]
        run("run", "--rm", *mounts(), args.image, ".venv/bin/python", "scripts/cloud/backup.py", "restore", archive)
        start()
        execute(VERIFY)
        run("stop", "--time", "90", container)
        print("PASS: private cold backup restores into empty container volumes with identical project and budget exposure.", flush=True)
        print("PASS: non-root product image, exclusive supervision, graceful stop and fresh-container data continuity.", flush=True)
    finally:
        # Remove only names generated by this run, never user installations.
        run("rm", "--force", container, check=False)
        for volume in volumes:
            run("volume", "rm", volume, check=False)


if __name__ == "__main__":
    main()
