#!/usr/bin/env python3
"""Explicit, bounded native-client compatibility test; never run from setup/CI."""
import getpass
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore.models import ClaudeBackend, Gateway
from explore.store import Budget, Client, JsonFile, atomic_local
from scripts.cloud.runtime import ROOT


def session_budget(client, limit=None):
    reference = ROOT / ".research/session-budget.json"
    reference.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    with reference.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if reference.exists():
            workspace = json.loads(reference.read_text())["workspace_id"]
            file = JsonFile(client, workspace, "execution/session-budget.json")
            existing, _ = file.read()
            return Budget(file, limit=existing["limit_cny"] if limit is None else limit,
                          prior=existing["prior_cny"], max_calls=existing["max_calls"])
        else:
            if limit is None:
                raise RuntimeError("Create a model budget explicitly with --budget-cny before the first paid run")
            workspace = client.request("POST", "/workspaces", {"title": "Authorized development model budget"})["id"]
        m0 = ROOT / ".runtime/m0-live/result.json"
        prior = json.loads(m0.read_text())["reserved_ceiling_cny"] if m0.exists() else 0
        budget = Budget(JsonFile(client, workspace, "execution/session-budget.json"), limit=limit, prior=prior)
        atomic_local(reference, {"workspace_id": workspace})
        return budget


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-cny", type=float, help="Explicit limit for a new pool; omit to reuse an existing pool")
    args = parser.parse_args()
    key = os.environ.get("DEEPSEEK_API_KEY") or getpass.getpass("DeepSeek API key (hidden): ")
    budget = session_budget(Client(), limit=args.budget_cny)
    gateway = Gateway(key, budget)
    call_id = "native-compat-" + uuid.uuid4().hex
    try:
        result = ClaudeBackend(ROOT, gateway).call(call_id, [
            {"question": "A shared file is read at version 1 by two workers. The update checks only its id, not its version. What concurrency condition should an atomic claim enforce?",
             "format": '{"condition":"one concise sentence","unknown":"one remaining limitation"}'}
        ], ROOT / ".research/native-probe")
        atomic_local(ROOT / ".runtime/native-cli-probe.json", {"call_id": call_id, "result": result,
                     "cli_version": "2.1.310", "tools": [], "max_supplier_requests": 1})
        print(json.dumps({"passed": True, "result": result}, ensure_ascii=False))
    finally:
        gateway.close()
