"""Frozen pilot packs, repeatable controls and blinded review over existing projects."""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import fcntl
import hashlib
import hmac
import json
from pathlib import Path
import random
import re
import secrets
import uuid

from .credentials import model_key
from scripts.cloud.runtime import ROOT
from .assessments import digest
from .engine import MODES, Project, source_snapshot
from .models import MODEL, OUTPUT_TOKENS, SimulatedBackend
from .policy import normalize
from .store import Client, Conflict, JsonFile, atomic_local

VARIANTS = {mode: {"mode": mode, "policy": normalize()} for mode in MODES}
VARIANTS.update({
    "no_peer_critique": {"mode": "collaborative", "policy": normalize({"peer_critique": False})},
    "fixed_directions": {"mode": "collaborative", "policy": normalize({"direction_changes": False})},
    "no_execution_failure_memory": {"mode": "collaborative", "policy": normalize({"execution_failure_memory": False})},
})
DIMENSIONS = ("question_clarity", "explanation_coverage", "counterexamples", "evidence_scope", "continuity", "useful_next_steps")


def runtime_manifest():
    paths = ["explore/engine.py", "explore/models.py", "explore/memory.py", "explore/reviews.py",
             "explore/store.py", "explore/policy.py", "explore/bootstrap.py", "explore/cross_memory.py",
             "explore/subagents.py", "explore/evaluation.py", "scripts/pi_runner.mjs", "scripts/subagents_runner.mjs",
             "cloud/versions.json", "cloud/package-lock.json", "cloud/pi/package-lock.json", "cloud/subagents/package-lock.json"]
    paths += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "cloud/patches").glob("*")) if p.is_file()]
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,23}", value) is None:
        raise ValueError("Use a 1–24 character lowercase identifier")
    return value


def freeze_pack(path, *, repeats=3, variants=None, seed=None):
    """No service, credentials or models are needed to freeze an evaluation."""
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Configure 1–10 repeats; fewer than three are case studies")
    variants = list(VARIANTS) if variants is None else list(variants)
    if not variants or len(set(variants)) != len(variants) or any(v not in VARIANTS for v in variants):
        raise ValueError("Choose unique documented control/ablation variants")
    tasks = raw.get("tasks", [])
    if not 8 <= len(tasks) <= 10 or sum(t.get("kind") == "open" for t in tasks) < (len(tasks) + 1) // 2:
        raise ValueError("The pilot needs 8–10 tasks with at least half open-ended")
    if len({identifier(t["id"]) for t in tasks}) != len(tasks):
        raise ValueError("Task identifiers must be unique")
    frozen_tasks = []
    for task in tasks:
        if (task.get("kind") not in ("open", "checkable") or not task.get("question", "").strip()
                or not task.get("known_disputes") or not task.get("rubric")
                or not task.get("second_round_focus", "").strip()
                or (task["kind"] == "checkable" and not task.get("expected_checks"))):
            raise ValueError("Each task needs a question, disputes, rubric and any deterministic expectations")
        snapshots = []
        for index, entry in enumerate(task.get("sources", [])):
            source_path = (path.parent / entry["path"]).resolve()
            if not source_path.is_relative_to(path.parent):
                raise ValueError("Pack materials must remain below the task-pack directory")
            snapshot = source_snapshot("source" + str(index), entry["title"], str(source_path), 1, 80)
            snapshot["path"] = entry["path"]
            snapshots.append(snapshot)
        frozen_tasks.append({**copy.deepcopy(task), "sources": snapshots})
    protocol = {"kind": "evaluation_protocol_v1", "pack_version": raw["version"],
                "tasks": frozen_tasks, "variants": {v: copy.deepcopy(VARIANTS[v]) for v in variants},
                "repeats": repeats, "rounds": 2, "max_invocations_per_round": 12, "max_concurrency": 2,
                "model": MODEL, "max_output_tokens": OUTPUT_TOKENS,
                "materials": "frozen_local_snapshots_only", "aggregation": "deterministic_export_no_model",
                "sampling": {"rule": "hash_order_of_post_ids", "maximum_findings_per_case": 5},
                "review_dimensions": list(DIMENSIONS), "blind_order_seed": seed or secrets.token_hex(16),
                "qualification": "Equal call ceilings are not equal actual spend; synthetic materials are not field observations. The failure-memory ablation hides execution-failure notes only."}
    protocol["runtime_manifest"] = runtime_manifest()
    protocol["runtime_sha256"] = digest(protocol["runtime_manifest"])
    return {"protocol": protocol, "protocol_sha256": digest(protocol)}


def validate_frozen(frozen, *, require_runtime=False):
    if digest(frozen["protocol"]) != frozen.get("protocol_sha256"):
        raise ValueError("Frozen evaluation protocol was modified")
    protocol = frozen["protocol"]
    if (type(protocol.get("repeats")) is not int or not 1 <= protocol["repeats"] <= 10
            or not 8 <= len(protocol.get("tasks", [])) <= 10
            or not isinstance(protocol.get("variants"), dict) or not protocol["variants"]
            or any(key not in VARIANTS or value != VARIANTS[key] for key, value in protocol["variants"].items())):
        raise ValueError("Frozen task/repetition/control bounds differ from the supported pilot")
    if require_runtime and (protocol["model"] != MODEL or protocol["max_output_tokens"] != OUTPUT_TOKENS):
        raise ValueError("The frozen model/output bound differs from this runtime")
    if require_runtime and (not protocol.get("runtime_manifest") or
            protocol.get("runtime_sha256") != digest(runtime_manifest()) or
            protocol["runtime_manifest"] != runtime_manifest()):
        raise ValueError("Frozen execution code/dependencies differ or are unbound; preserve historical results and freeze a new campaign")
    for task in protocol["tasks"]:
        identifier(task["id"])
        for source in task["sources"]:
            identifier(source["id"])
            if hashlib.sha256("\n".join(source["lines"]).encode()).hexdigest() != source["sha256"]:
                raise ValueError("Frozen source fingerprint differs from its text")
    return protocol


def assert_case_inputs(state, protocol, case):
    task = next(t for t in protocol["tasks"] if t["id"] == case["task_id"])
    variant = protocol["variants"][case["variant"]]
    expected_agents = 1 if variant["mode"] in ("single", "multiple_perspectives") else 3
    if (state["name"] != case["project_name"] or state["mode"] != variant["mode"]
            or normalize(state.get("semantic_policy")) != variant["policy"]
            or len(state["agents"]) != expected_agents or state.get("max_concurrency", 2) != protocol.get("max_concurrency", 2)
            or state["max_rounds"] != protocol["rounds"]
            or state["max_invocations_per_round"] != protocol["max_invocations_per_round"]
            or [(s["id"], s["title"], s["sha256"]) for s in state["sources"].values()] !=
               [(s["id"], s["title"], s["sha256"]) for s in task["sources"]]
            or state.get("cross_project_memory")
            or any(q["text"] != (task["question"] if q["number"] == 1 else task["second_round_focus"])
                   or q["number"] > 2 or q["author"] != "evaluation_script" for q in state["question_revisions"])):
        raise Conflict("Case configuration or semantic intervention differs from the frozen protocol")


class Campaign:
    """Own evaluation design/reviews; Project remains the sole execution owner."""
    def __init__(self, client, directory):
        self.client, self.directory = client, Path(directory)
        metadata = json.loads((self.directory / "metadata.json").read_text())
        self.file = JsonFile(client, metadata["workspace_id"], "evaluation/campaign.json")

    @classmethod
    def prepare(cls, client, name, frozen):
        identifier(name)
        protocol = validate_frozen(frozen, require_runtime=True)
        directory = ROOT / ".research/evaluations" / name
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / "prepare.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            metadata = directory / "metadata.json"
            if not metadata.exists():
                workspace = client.request("POST", "/workspaces", {"title": "Evaluation " + name})["id"]
                atomic_local(metadata, {"workspace_id": workspace})
            campaign = cls(client, directory)
            cases = []
            for task in protocol["tasks"]:
                for variant in protocol["variants"]:
                    for repeat in range(protocol["repeats"]):
                        identity = digest([frozen["protocol_sha256"], task["id"], variant, repeat, name])
                        blind_id = hmac.new(protocol["blind_order_seed"].encode(), identity.encode(), "sha256").hexdigest()[:20]
                        cases.append({"id": identity, "project_name": "ev_" + identity[:20],
                                      "task_id": task["id"], "variant": variant, "repeat": repeat + 1,
                                      "blind_id": blind_id})
            campaign.file.create({"kind": "evaluation_v1", "name": name, "frozen": frozen,
                                  "cases": cases, "reviews": {}, "backend": None})
            if campaign.file.read()[0]["frozen"] != frozen:
                raise Conflict("This campaign is already bound to a different frozen protocol")
            return campaign

    def project(self, state, case):
        protocol = validate_frozen(state["frozen"], require_runtime=True)
        task = next(t for t in protocol["tasks"] if t["id"] == case["task_id"])
        variant = protocol["variants"][case["variant"]]
        directory = ROOT / ".research" / case["project_name"]
        sources = []
        for source in task["sources"]:
            path = self.directory / "materials" / task["id"] / (source["id"] + ".md")
            text = "\n".join(source["lines"])
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.exists() and path.read_text() != text:
                raise ValueError("Preserve the altered local evaluation material; it differs from the frozen pack")
            path.write_text(text, encoding="utf-8")
            sources.append((source["id"], source["title"], str(path), 1, 80))
        if directory.exists():
            project = Project(self.client, directory)
        else:
            project = Project.create(self.client, case["project_name"], mode=variant["mode"],
                question=task["question"], sources=sources, question_author="evaluation_script",
                semantic_policy=variant["policy"], max_rounds=protocol["rounds"],
                max_invocations_per_round=protocol["max_invocations_per_round"])
        binding = {"campaign_workspace": self.file.workspace, "case_id": case["id"],
                   "protocol_sha256": state["frozen"]["protocol_sha256"]}
        def bind(current):
            if current.get("evaluation_binding") is not None:
                if current["evaluation_binding"] != binding:
                    raise Conflict("Project belongs to a different evaluation case")
                return True
            if (current["calls"] or current["mode"] != variant["mode"]
                    or normalize(current.get("semantic_policy")) != variant["policy"]
                    or current["max_rounds"] != protocol["rounds"]
                    or current["max_invocations_per_round"] != protocol["max_invocations_per_round"]
                    or current["question_revisions"][0]["text"] != task["question"]
                    or [s["sha256"] for s in current["sources"].values()] != [s["sha256"] for s in task["sources"]]):
                raise Conflict("Existing project differs from the frozen case")
            current["evaluation_binding"] = binding
            return True
        project.file.update("bind-evaluation:" + case["id"], bind)
        return project, task

    def advance(self, backend, *, case_id=None, maximum_cases=1):
        if type(maximum_cases) is not int or not 1 <= maximum_cases <= 1000:
            raise ValueError("Advance 1–1000 cases per invocation")
        # This lock serializes the local evaluation driver, not model execution.
        # Existing Project owners/claims govern every action and recovery.
        with (self.directory / "advance.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def bind_backend(state):
                if state["backend"] not in (None, backend.name):
                    raise Conflict("Use a separate campaign for another execution backend")
                state["backend"] = backend.name
            self.file.update("bind-backend:" + backend.name, bind_backend)
            state, _ = self.file.read()
            selected = [c for c in state["cases"] if case_id is None or c["id"] == case_id]
            if not selected:
                raise ValueError("Unknown evaluation case")
            advanced = []
            for case in selected:
                project, task = self.project(state, case)
                current, _ = project.file.read()
                assert_case_inputs(current, state["frozen"]["protocol"], case)
                if len(current["rounds"]) == state["frozen"]["protocol"]["rounds"] and all(
                        r["status"] == "completed" for r in current["rounds"]):
                    continue
                if current["status"] != "active":
                    raise RuntimeError("Inspect/reconcile the blocked project before continuing the evaluation")
                while len(current["rounds"]) < state["frozen"]["protocol"]["rounds"] or any(
                        r["status"] != "completed" for r in current["rounds"]):
                    if current["rounds"] and current["rounds"][-1]["status"] == "completed":
                        def steer(s):
                            if len(s["question_revisions"]) == 1:
                                s["question_revisions"].append({"number": 2, "text": task["second_round_focus"], "author": "evaluation_script"})
                                project.event(s, "steer", question_revision=2)
                        project.file.update("evaluation-focus:" + case["id"], steer)
                    project.advance(backend, evaluation_case=current["evaluation_binding"])
                    current, _ = project.file.read()
                    if current["status"] != "active" or any(r["status"] == "cancelled" for r in current["rounds"]):
                        raise RuntimeError("Case paused or cancelled; preserve it for explicit reconciliation")
                project.export(project.directory / "exports")
                advanced.append(case["id"])
                if len(advanced) >= maximum_cases:
                    break
            return advanced

    def export(self, destination):
        """Blinded review views and separate key/report; never model aggregation."""
        state, _ = self.file.read()
        protocol = validate_frozen(state["frozen"])
        destination = Path(destination)
        cases, views, key = [], [], {}
        ledger = {}
        budget_reference = ROOT / ".research/session-budget.json"
        if budget_reference.exists():
            workspace = json.loads(budget_reference.read_text())["workspace_id"]
            ledger = JsonFile(self.client, workspace, "execution/session-budget.json").read()[0]["requests"]
        for case in state["cases"]:
            directory = ROOT / ".research" / case["project_name"]
            row = {**case, "status": "not_started", "attempts": 0}
            if (directory / "run_metadata.json").exists():
                project = Project(self.client, directory)
                snapshot = project.export(directory / "exports")
                current = snapshot["state"]
                calls = [*current["calls"].values(), *current.get("retired_calls", {}).values()]
                row.update(status=("completed" if len(current["rounds"]) == protocol["rounds"] and
                    all(r["status"] == "completed" for r in current["rounds"]) else current["status"]),
                    kind=snapshot["kind"], attempts=len(calls),
                    completed_attempts=sum(c["status"] == "completed" for c in calls),
                    failed_attempts=sum(c["status"] in ("failed", "failed_before_dispatch", "invalid_output") for c in calls),
                    unknown_attempts=sum(c["status"] == "unknown" for c in calls),
                    direction_changes=len(current["direction_history"]), reviews=len(current.get("reviews", [])))
                receipts = [ledger[c["id"]] for c in calls if c["id"] in ledger]
                row["supplier_usage"] = {"requests": len(receipts),
                    "input_tokens": sum(r.get("usage", {}).get("input_tokens", 0) for r in receipts),
                    "output_tokens": sum(r.get("usage", {}).get("output_tokens", 0) for r in receipts),
                    "unknown_requests": sum(r["state"] == "unknown" for r in receipts),
                    "exposure_cny": sum(r.get("settled_cny", r["reserved_cny"]) for r in receipts),
                    "qualification": "Admission accounting, not a supplier invoice; missing usage is not zero cost"}
                posts = [p for p in snapshot["posts"] if p["phase"] == "reflect"]
                findings = [json.loads(p["post"]["content"]) for p in posts]
                sample = sorted(range(len(posts)), key=lambda i: digest([state["frozen"]["protocol_sha256"], case["id"], posts[i]["id"]]))[:protocol["sampling"]["maximum_findings_per_case"]]
                row["sampled_post_ids"] = [posts[i]["id"] for i in sample]
                task = next(t for t in protocol["tasks"] if t["id"] == case["task_id"])
                # A partial mask: redact explicit protocol/control metadata. Text
                # may still reveal collaboration; do not promise perfect blinding.
                view = {"case_id": case["blind_id"], "task_id": case["task_id"],
                        "questions": [{"number": q["number"], "text": q["text"]} for q in current["question_revisions"]],
                        "findings": [{k: copy.deepcopy(f[k]) for k in
                                      ("finding", "evidence", "unresolved", "claim_kind", "revisit_when") if k in f} for f in findings],
                        "sources": snapshot["sources"], "dimensions": list(DIMENSIONS),
                        "sampled_finding_indexes": sample, "rubric": task["rubric"],
                        "expected_checks": task.get("expected_checks", []),
                        "qualification": "Configuration labels hidden; prose or output size may reveal the condition. Incomplete cases are retained."}
                views.append(view)
            cases.append(row)
            key[case["blind_id"]] = case
        random.Random(protocol["blind_order_seed"]).shuffle(views)
        atomic_local(destination / "review-packet.json", {"protocol_sha256": state["frozen"]["protocol_sha256"], "cases": views})
        atomic_local(destination / "private-key.json", key)
        report = {"protocol_sha256": state["frozen"]["protocol_sha256"], "backend": state["backend"], "cases": cases,
                  "frozen_runtime_sha256": protocol.get("runtime_sha256"),
                  "current_runtime_matches_frozen": protocol.get("runtime_sha256") == digest(runtime_manifest()),
                  "case_status_counts": dict(Counter(c["status"] for c in cases)),
                  "human_reviews": list(state["reviews"].values()),
                  "repeats": protocol["repeats"], "kind": "mechanical_fixture" if state["backend"] == "simulated" else "evaluation_execution_records",
                  "qualification": "No automatic quality score. Missing reviews and failed/incomplete cases are retained; no collaboration benefit is inferred."}
        groups = []
        for task in protocol["tasks"]:
            for variant in protocol["variants"]:
                rows = [r for r in cases if r["task_id"] == task["id"] and r["variant"] == variant]
                reviewed = [r for r in state["reviews"].values() if r["blind_id"] in {row["blind_id"] for row in rows}]
                groups.append({"task_id": task["id"], "variant": variant,
                    "repeats_configured": len(rows), "completed": sum(r["status"] == "completed" for r in rows),
                    "statuses": dict(Counter(r["status"] for r in rows)),
                    "actual_attempts": [r["attempts"] for r in rows],
                    "exposure_cny": [r.get("supplier_usage", {}).get("exposure_cny") for r in rows],
                    "reviewer_count": len({r["reviewer"] for r in reviewed}),
                    "review_count": len(reviewed),
                    "dimension_judgments": {d: dict(Counter(r["ratings"][d] for r in reviewed)) for d in DIMENSIONS}})
        report["task_variant_groups"] = groups
        atomic_local(destination / "report.json", report)
        lines = ["# 开放探索对照报告", "", f"记录性质：{report['kind']}；模型：{protocol['model']}；后端：{state['backend']}。",
                 f"协议指纹：{report['protocol_sha256']}。每个任务/配置预设重复 {protocol['repeats']} 次。",
                 "所有配置使用相同调用上限和审计/恢复设施；实际调用和费用可能不同。缺失用量不是零费用。",
                 "模拟运行只检验机制；没有人工评阅时，不判断质量收益。少于三次重复仅视作个案。", "",
                 "| 任务 | 配置 | 完成/预设 | 各次实际调用 | 评阅者数 | 评阅记录 |", "| --- | --- | --- | --- | --- | --- |"]
        lines.extend(f"| {g['task_id']} | {g['variant']} | {g['completed']}/{g['repeats_configured']} | {g['actual_attempts']} | {g['reviewer_count']} | {g['review_count']} |" for g in groups)
        lines.extend(["", "## 评阅理由与分歧", ""])
        for review in state["reviews"].values():
            lines.extend([f"- {review['blind_id']} · {review['reviewer']}：{review['reason']}",
                          f"  - 各维度判断：{json.dumps(review['ratings'], ensure_ascii=False)}"])
        lines.extend(["", "## 未完成与失败案例", ""])
        lines.extend(f"- {r['task_id']} / {r['variant']} / 重复 {r['repeat']}：{r['status']}；未知调用 {r.get('unknown_attempts', 0)}。"
                     for r in cases if r["status"] != "completed")
        (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

    def review(self, blind_id, reviewer, ratings, reason, review_id=None):
        if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Review attribution and concrete reasoning are required")
        if not isinstance(ratings, dict) or set(ratings) != set(DIMENSIONS) or any(v not in ("useful", "mixed", "weak", "uncertain") for v in ratings.values()):
            raise ValueError("Rate every frozen review dimension with useful/mixed/weak/uncertain")
        review_id = review_id or uuid.uuid4().hex
        record = {"id": review_id, "blind_id": blind_id, "reviewer": reviewer.strip(), "ratings": ratings, "reason": reason.strip()}
        def save(state):
            if blind_id not in {c["blind_id"] for c in state["cases"]}:
                raise ValueError("Review refers to an unknown blinded case")
            old = state["reviews"].get(review_id)
            if old is not None and old != record:
                raise Conflict("Review ID already belongs to another judgment")
            state["reviews"][review_id] = copy.deepcopy(record)
            return review_id
        return self.file.update("human-review:" + digest(record), save)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("pack")
    freeze.add_argument("output")
    freeze.add_argument("--repeats", type=int, default=3)
    freeze.add_argument("--variant", action="append", choices=VARIANTS)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("name")
    prepare.add_argument("frozen")
    for command in ("advance", "export", "review"):
        sub = commands.add_parser(command)
        sub.add_argument("name")
        if command == "advance":
            sub.add_argument("--maximum-cases", type=int, default=1)
            sub.add_argument("--case-id")
            sub.add_argument("--live", action="store_true")
            sub.add_argument("--budget-cny", type=float)
            sub.add_argument("--budget-max-calls", type=int, help="Request cap for a new shared pool; cannot overwrite existing limits")
            sub.add_argument("--backend", choices=("pi", "pi-subagents", "claude"), default="pi")
        if command == "review":
            sub.add_argument("blind_id")
            sub.add_argument("ratings_file")
            sub.add_argument("--reviewer", required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--review-id")
    args = parser.parse_args()
    if args.command == "freeze":
        frozen = freeze_pack(args.pack, repeats=args.repeats, variants=args.variant)
        atomic_local(Path(args.output), frozen)
        print(frozen["protocol_sha256"])
        return
    client = Client()
    if args.command == "prepare":
        campaign = Campaign.prepare(client, args.name, json.loads(Path(args.frozen).read_text()))
        print(campaign.directory)
        return
    identifier(args.name)
    campaign = Campaign(client, ROOT / ".research/evaluations" / args.name)
    if args.command == "advance":
        if not args.live:
            print(campaign.advance(SimulatedBackend(), case_id=args.case_id, maximum_cases=args.maximum_cases))
        else:
            import getpass
            import os
            from scripts.probe_native import session_budget
            from .models import ClaudeBackend, Gateway, PiBackend
            from .subagents import SubagentsBackend
            budget = session_budget(client, limit=args.budget_cny, max_calls=args.budget_max_calls)
            key = model_key() or getpass.getpass("DeepSeek API key (hidden): ")
            gateway = Gateway(key, budget)
            try:
                selected = {"pi": PiBackend, "pi-subagents": SubagentsBackend, "claude": ClaudeBackend}[args.backend]
                print(campaign.advance(selected(ROOT, gateway), case_id=args.case_id, maximum_cases=args.maximum_cases))
            finally:
                gateway.close()
    elif args.command == "review":
        print(campaign.review(args.blind_id, args.reviewer, json.loads(Path(args.ratings_file).read_text()), args.reason, args.review_id))
    else:
        print(json.dumps(campaign.export(campaign.directory / "exports"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(f"Stopped: {error}")
