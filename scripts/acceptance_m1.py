#!/usr/bin/env python3
"""Run one explicit real-model case, with a shared already-authorized budget."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore.credentials import model_key
from explore.engine import MODES, Project
from explore.models import ClaudeBackend, Gateway, PiBackend
from explore.subagents import SubagentsBackend
from explore.store import Client, atomic_local
from scripts.probe_native import session_budget
from scripts.cloud.runtime import ROOT


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--mode", choices=MODES, default="collaborative")
    parser.add_argument("--rounds", type=int, choices=(1, 2), default=2)
    parser.add_argument("--project", help="Continue an existing case without repeating finished calls")
    parser.add_argument("--budget-cny", type=float, help="Explicit limit for a new pool; omit to reuse an existing pool")
    parser.add_argument("--backend", choices=("pi", "claude", "pi-subagents"), default="pi")
    args = parser.parse_args()
    key = model_key() or getpass.getpass("DeepSeek API key (hidden): ")
    client = Client()
    budget = session_budget(client, limit=args.budget_cny)
    project = (Project(client, ROOT / ".research" / args.project) if args.project else
               Project.create(client, "live_" + args.mode[:4] + "_" + uuid.uuid4().hex[:8], mode=args.mode))
    if project.file.read()[0]["mode"] != args.mode:
        raise RuntimeError("Requested evaluation mode differs from the authoritative project state")
    if args.project:
        project.reconcile(budget)
        if project.file.read()[0]["status"] == "blocked":
            project.control("resume")
    print("Created", project.directory.name, flush=True)
    gateway = Gateway(key, budget)

    selected_backend = {"pi": PiBackend, "claude": ClaudeBackend, "pi-subagents": SubagentsBackend}[args.backend]
    class TracingBackend(selected_backend):
        def call(self, call_id, *args, **kwargs):
            output = super().call(call_id, *args, **kwargs)
            print("Received", call_id, flush=True)
            return output

    try:
        backend = TracingBackend(ROOT, gateway)
        for round_number in range(args.rounds):
            rounds = project.file.read()[0]["rounds"]
            if len(rounds) > round_number and rounds[round_number]["status"] == "completed":
                continue
            if round_number and len(rounds) == round_number:
                project.control("pause")
                project.control("steer", "重点核查长期个人使用中的用户改向、旧结论的适用范围，以及如何避免共享意见形成引用循环。", author="evaluation_script")
                subprocess.run([sys.executable, "scripts/cloud/runtime.py", "stop"], cwd=ROOT, check=True)
                subprocess.run([sys.executable, "scripts/cloud/runtime.py", "start"], cwd=ROOT, check=True)
                project = Project(client, project.directory)
                project.control("resume")
            project.advance(backend)
            project.export(project.directory / "exports")
            print("Completed round", round_number + 1, flush=True)
        state, _ = project.file.read()
        pool, _ = budget.file.read()
        report = {"project": project.directory.name, "mode": state["mode"],
                  "rounds": state["rounds"], "post_count": len(state["posts"]),
                  "applied_changes": len(state["direction_history"]),
                  "pool_exposure_cny": budget.exposure(pool), "budget_workspace": budget.file.workspace}
        atomic_local(project.directory / "acceptance.json", report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        gateway.close()
