"""Materialize a narrowly patched upstream launcher; never edit its pinned checkout."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.cloud.runtime import ROOT, STATE
from .store import atomic_local

ADAPTED = STATE / "adapted/AutoScientists"


def prepare():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "prepare-adapter.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _prepare_owned()


def _prepare_owned():
    source = STATE / "upstream/AutoScientists"
    manifest = json.loads((ROOT / "cloud/patches/autoscientists-open-task.json").read_text())
    pinned = json.loads((ROOT / "cloud/versions.json").read_text())["upstream"]["commit"]
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() != pinned:
        raise RuntimeError("Upstream checkout is not the pinned commit")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise RuntimeError("Preserve upstream source edits before preparing the reviewed adapter")
    if hashlib.sha256((source / "launch.py").read_bytes()).hexdigest() != manifest["source_sha256"]:
        raise RuntimeError("Upstream launcher differs from the reviewed source")
    if ADAPTED.exists():
        expected = manifest["adapted_sha256"]
        if hashlib.sha256((ADAPTED / "launch.py").read_bytes()).hexdigest() != expected:
            raise RuntimeError("Adapted launcher has unknown edits; preserve them before rebuilding")
    else:
        ADAPTED.mkdir(parents=True, mode=0o700)
        for filename in ("launch.py", "README.md", "runbook.md", "requirements.txt"):
            shutil.copy2(source / filename, ADAPTED / filename)
        shutil.copytree(source / "system", ADAPTED / "system", ignore=shutil.ignore_patterns("__pycache__", ".key", "*.key", ".env"))
        subprocess.run(["git", "apply", f"--directory={ADAPTED.relative_to(ROOT)}",
                        str(ROOT / "cloud/patches/autoscientists-open-task.patch")], cwd=ROOT, check=True)
    for overlay in (ROOT / "cloud/overlays").glob("*.md"):
        shutil.copy2(overlay, ADAPTED / "system/templates" / overlay.name)
    if (ADAPTED / ".key").exists():
        raise RuntimeError("An unexpected cached credential would override the checkout-owned service token; preserve and inspect it")
    return ADAPTED


def launch(client, name, question=None, participants=3):
    if not name or len(name) > 24 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in name):
        raise ValueError("Project name must be 1–24 lowercase letters, digits or underscores")
    locks = STATE / "bootstrap-locks"
    locks.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (locks / (name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _launch_owned(client, name, question, participants)


def _launch_owned(client, name, question=None, participants=3):
    if not name or len(name) > 24 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in name):
        raise ValueError("Project name must be 1–24 lowercase letters, digits or underscores")
    destination = ROOT / ".research" / name
    if destination.exists():
        raise RuntimeError("Project directory already exists; use status/continue instead")
    launcher = prepare()
    task = ROOT / "examples/open-exploration"
    if type(participants) is not int or not 1 <= participants <= 8:
        raise ValueError("Choose 1–8 exploration participants")
    if question is not None or participants != 3:
        question = question or "如何让本项目从多智能体演示走向可持续、可核对的开放探索？"
        if not isinstance(question, str) or not question.strip():
            raise ValueError("An open question must contain text")
        task = STATE / "open-tasks" / name
        task.mkdir(parents=True, exist_ok=True, mode=0o700)
        (task / "TASK.md").write_text("---\ntask_type: open_exploration\nname: " + name +
            f"\nparticipants: {participants}\n---\n\n" + question + "\n\nPreserve competing explanations and unresolved questions. Numeric goals, datasets, experiments and papers are optional.\n")
        shutil.copy2(ROOT / "examples/open-exploration/LAUNCH.md", task / "LAUNCH.md")
    environment = os.environ.copy()
    # The release widens workshop names but still stores denormalized slugs in
    # VARCHAR(24) workspace/post columns. Keep native IDs within that boundary.
    workshop = "open_" + name[:10] + "_" + hashlib.sha256(name.encode()).hexdigest()[:8]
    environment.update(CLAWINSTITUTE_API=client.base, CLAWINSTITUTE_TOKEN=client.token,
                       WORKSHOP_NAME=workshop, WORKSHOP_DISPLAY_NAME=name,
                       WORKSHOP_DESCRIPTION="Bounded open exploration; no scientific compute")
    # The upstream materializer writes only into its new private run directory.
    result = subprocess.run([sys.executable, str(launcher / "launch.py"), name, "--task",
                            str(task), "--output-dir", str(destination.parent)],
                           cwd=ROOT, env=environment, capture_output=True, text=True, timeout=90,
                           preexec_fn=lambda: os.umask(0o077))
    if result.returncode:
        atomic_local(STATE / "bootstrap-errors" / f"{name}.json", {
            "returncode": result.returncode, "stdout": result.stdout.replace(client.token, "<redacted>"),
            "stderr": result.stderr.replace(client.token, "<redacted>")})
        raise RuntimeError("Upstream materialization failed; preserve the partial project for inspection")
    metadata = json.loads((destination / "run_metadata.json").read_text())
    if metadata["task_type"] != "open_exploration" or len(metadata["agents"]) != participants:
        raise RuntimeError("Upstream materialization did not produce the requested exploration identities")
    if (destination / "champion").exists() or (destination / "repo").exists():
        raise RuntimeError("Open task unexpectedly materialized a scientific training repository")
    atomic_local(destination / "bootstrap-check.json", {"upstream_commit": "c71a92343b9a488ed10134be805845b9473ad18f",
                 "materializer": "patched-upstream-launch.py", "model_calls": 0})
    return destination, metadata


if __name__ == "__main__":
    print(prepare())
